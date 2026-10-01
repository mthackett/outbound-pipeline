import re
import json
import uuid
import hashlib
from typing import List, Dict, Any, Optional, Tuple, Union

from job_pipeline.domain.models import (
    TelemetryRule,
    TelemetryFinding,
    TELEMETRY_RULE_CATEGORIES,
    TELEMETRY_MATCH_MODES,
    DEFAULT_TELEMETRY_RULES
)
from job_pipeline.logger import log_telemetry, log_warn


# Global in-memory cache to avoid repeated LLM calls on identical job description text & rules
_TELEMETRY_EXTRACTION_CACHE: Dict[str, Any] = {}


class TelemetryService:
    """Core domain service for deterministic and semantic telemetry rule evaluation."""

    @staticmethod
    def validate_rule(rule: TelemetryRule) -> Tuple[bool, Optional[str]]:
        """
        Validates a telemetry rule for correctness before execution.
        Returns (is_valid, error_message).
        """
        if not rule.id or not str(rule.id).strip():
            return False, "Rule missing stable identifier (id)."

        if not rule.name or not str(rule.name).strip():
            return False, f"Rule '{rule.id}' missing display name."

        category = str(rule.category).strip().lower()
        if category not in TELEMETRY_RULE_CATEGORIES:
            return False, f"Rule '{rule.id}' has invalid category '{rule.category}'. Must be one of: {', '.join(TELEMETRY_RULE_CATEGORIES)}."

        match_mode = str(rule.match_mode).strip().lower()
        if match_mode not in TELEMETRY_MATCH_MODES:
            return False, f"Rule '{rule.id}' has invalid match_mode '{rule.match_mode}'. Must be one of: {', '.join(TELEMETRY_MATCH_MODES)}."

        if match_mode in ("token", "phrase"):
            clean_patterns = [p.strip() for p in (rule.patterns or []) if p and p.strip()]
            if not clean_patterns:
                return False, f"Rule '{rule.id}' ({match_mode}) must contain at least one non-empty keyword/pattern."

        elif match_mode == "regex":
            clean_patterns = [p.strip() for p in (rule.patterns or []) if p and p.strip()]
            if not clean_patterns:
                return False, f"Rule '{rule.id}' (regex) must contain at least one regex pattern."
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            for pat in clean_patterns:
                try:
                    re.compile(pat, flags)
                except re.error as e:
                    return False, f"Invalid regex pattern '{pat}' in rule '{rule.id}': {e}"

        elif match_mode == "concept":
            if not rule.concept_description or not str(rule.concept_description).strip():
                return False, f"Rule '{rule.id}' (concept) must contain a non-empty concept_description."

        return True, None

    @classmethod
    def normalize_rule_dict(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes any dictionary representation (including legacy warning rules)
        into a consistent structured telemetry rule dictionary.
        """
        data = dict(raw)

        # 1. Stable ID
        if not data.get("id"):
            data["id"] = f"warn-{uuid.uuid4().hex[:6]}"

        # 2. Display Name
        data["name"] = data.get("name", "Unnamed Telemetry Rule")

        # 3. Synchronize patterns and legacy keywords
        patterns = list(data.get("patterns") or [])
        keywords = list(data.get("keywords") or [])
        if keywords and not patterns:
            patterns = keywords
        elif patterns and not keywords:
            keywords = patterns
        data["patterns"] = patterns
        data["keywords"] = keywords

        # 4. Resolve Category vs Domain Category vs Severity
        raw_cat = str(data.get("category", "")).strip().lower()
        raw_sev = str(data.get("severity", "")).strip().lower()

        if raw_cat in TELEMETRY_RULE_CATEGORIES:
            data["category"] = raw_cat
        elif raw_sev in TELEMETRY_RULE_CATEGORIES:
            data["category"] = raw_sev
            data["domain_category"] = data.get("category") or "Scope"
        elif raw_sev == "flag":
            data["category"] = "flag"
            data["domain_category"] = data.get("category") or "Scope"
        elif raw_sev == "warning":
            data["category"] = "warning"
            data["domain_category"] = data.get("category") or "Scope"
        else:
            data["category"] = "warning"
            if data.get("category") and data.get("category") not in TELEMETRY_RULE_CATEGORIES:
                data["domain_category"] = data["category"]

        if not data.get("domain_category"):
            data["domain_category"] = "Scope"

        # Update severity string for legacy consumers
        cat_lower = data["category"].lower()
        data["severity"] = "Flag" if cat_lower == "flag" else ("Benefit" if cat_lower == "benefit" else "Warning")

        # 5. Resolve Match Mode
        raw_mode = str(data.get("match_mode", "")).strip().lower()
        if raw_mode in TELEMETRY_MATCH_MODES:
            data["match_mode"] = raw_mode
        else:
            if patterns:
                # If any pattern contains spaces, treat as phrase, else token
                if any(" " in str(p).strip() for p in patterns):
                    data["match_mode"] = "phrase"
                else:
                    data["match_mode"] = "token"
            elif data.get("concept_description"):
                data["match_mode"] = "concept"
            else:
                data["match_mode"] = "token"

        # 6. Explanation
        if not data.get("explanation"):
            data["explanation"] = data.get("concept_description") or f"Triggered rule '{data['name']}'."

        # 7. Flags
        data["enabled"] = bool(data.get("enabled", True))
        data["case_sensitive"] = bool(data.get("case_sensitive", False))

        return data

    @classmethod
    def normalize_rule(cls, raw: Union[TelemetryRule, Dict[str, Any]]) -> TelemetryRule:
        """Converts input into a strongly typed, validated TelemetryRule."""
        if isinstance(raw, TelemetryRule):
            return raw
        norm_dict = cls.normalize_rule_dict(raw)
        return TelemetryRule(**norm_dict)

    @staticmethod
    def match_token(pattern: str, text: str, case_sensitive: bool = False) -> Optional[str]:
        """
        Boundary-aware exact token matching equivalent to \\btoken\\b.
        Uses lookarounds to correctly handle tokens with punctuation (e.g. 401(k), TS/SCI).
        Does NOT match arbitrary substrings (e.g. 'FAR' inside 'software' or 'farmer').
        """
        p_clean = pattern.strip()
        if not p_clean:
            return None
        flags = 0 if case_sensitive else re.IGNORECASE
        regex_pattern = r'(?<!\w)' + re.escape(p_clean) + r'(?!\w)'
        match = re.search(regex_pattern, text, flags)
        return match.group(0) if match else None

    @staticmethod
    def match_phrase(phrase: str, text: str, case_sensitive: bool = False) -> Optional[str]:
        """
        Boundary-aware phrase matching.
        Matches the multi-word phrase with whole-word boundaries at boundaries.
        """
        p_clean = phrase.strip()
        if not p_clean:
            return None
        flags = 0 if case_sensitive else re.IGNORECASE
        regex_pattern = r'(?<!\w)' + re.escape(p_clean) + r'(?!\w)'
        match = re.search(regex_pattern, text, flags)
        return match.group(0) if match else None

    @staticmethod
    def match_regex(pattern: str, text: str, case_sensitive: bool = False, rule_id: str = "") -> Optional[str]:
        """
        Regex matching with safe error catching and logging.
        Fails gracefully without crashing if regex is invalid.
        """
        p_clean = pattern.strip()
        if not p_clean:
            return None
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(p_clean, flags)
            match = compiled.search(text)
            return match.group(0) if match else None
        except re.error as e:
            log_warn(f"[WARN] Invalid telemetry regex for rule '{rule_id}': {e}")
            return None

    @classmethod
    def evaluate_deterministic_rule(cls, rule: TelemetryRule, text: str) -> Optional[TelemetryFinding]:
        """
        Evaluates a single deterministic rule (token, phrase, regex).
        Returns TelemetryFinding if matched, otherwise None.
        """
        if not rule.enabled:
            return None

        is_valid, err = cls.validate_rule(rule)
        if not is_valid:
            log_warn(f"[WARN] Skipping invalid telemetry rule '{rule.id}': {err}")
            return None

        mode = (rule.match_mode or "token").lower()
        if mode == "concept":
            # Semantic rules are evaluated via LLM, not deterministically
            return None

        matched_snippets: List[str] = []
        for pat in (rule.patterns or []):
            if not pat or not str(pat).strip():
                continue
            matched: Optional[str] = None
            if mode == "token":
                matched = cls.match_token(pat, text, case_sensitive=rule.case_sensitive)
            elif mode == "phrase":
                matched = cls.match_phrase(pat, text, case_sensitive=rule.case_sensitive)
            elif mode == "regex":
                matched = cls.match_regex(pat, text, case_sensitive=rule.case_sensitive, rule_id=rule.id)

            if matched and matched not in matched_snippets:
                matched_snippets.append(matched)

        if matched_snippets:
            primary_snippet = matched_snippets[0]
            reason_text = rule.explanation or f"Posting contains matching {mode} '{primary_snippet}'."
            return TelemetryFinding(
                rule_id=rule.id,
                rule_name=rule.name,
                category=rule.category.lower(),
                match_mode=mode,
                matched_text=", ".join(matched_snippets),
                reason=reason_text,
                domain_category=rule.domain_category
            )

        return None

    @classmethod
    def evaluate_deterministic_rules(
        cls,
        rules: List[Union[TelemetryRule, Dict[str, Any]]],
        text: str
    ) -> List[TelemetryFinding]:
        """
        Evaluates all active deterministic rules against text.
        Preserves all simultaneous findings (does not stop after first match).
        Emits structured logs.
        """
        normalized_rules = [cls.normalize_rule(r) for r in rules if (r.get("enabled", True) if isinstance(r, dict) else r.enabled)]
        deterministic_rules = [r for r in normalized_rules if (r.match_mode or "").lower() != "concept"]

        log_telemetry(f"Evaluating {len(deterministic_rules)} deterministic rules.")

        findings: List[TelemetryFinding] = []
        for rule in deterministic_rules:
            finding = cls.evaluate_deterministic_rule(rule, text)
            if finding:
                findings.append(finding)
                cat_lower = finding.category.lower()
                if cat_lower == "flag":
                    log_telemetry(f"Flag matched: {finding.rule_id} ('{finding.rule_name}')")
                elif cat_lower == "benefit":
                    log_telemetry(f"Benefit matched: {finding.rule_id} ('{finding.rule_name}')")
                else:
                    log_telemetry(f"Warning matched: {finding.rule_id} ('{finding.rule_name}')")

        return findings

    @staticmethod
    def compute_telemetry_status(findings: List[TelemetryFinding]) -> str:
        """
        Computes negative-severity status:
        - One or more flags -> 'red'
        - One or more warnings (no flags) -> 'yellow'
        - No warnings or flags -> 'green'
        Benefits do not alter this status.
        """
        has_flags = any((f.category or "").lower() == "flag" for f in findings)
        if has_flags:
            return "red"
        has_warnings = any((f.category or "").lower() == "warning" for f in findings)
        if has_warnings:
            return "yellow"
        return "green"

    @staticmethod
    def split_findings(
        findings: List[TelemetryFinding]
    ) -> Tuple[List[TelemetryFinding], List[TelemetryFinding], List[TelemetryFinding]]:
        """Splits findings into (flags, warnings, benefits)."""
        flags: List[TelemetryFinding] = []
        warnings: List[TelemetryFinding] = []
        benefits: List[TelemetryFinding] = []
        for f in findings:
            cat = (f.category or "warning").lower()
            if cat == "flag":
                flags.append(f)
            elif cat == "benefit":
                benefits.append(f)
            else:
                warnings.append(f)
        return flags, warnings, benefits

    @staticmethod
    def compute_cache_key(raw_jd: str, rules: List[Dict[str, Any]]) -> str:
        """Computes deterministic cache key from raw JD text and active semantic rules."""
        semantic_subset = [
            {"id": r.get("id"), "concept": r.get("concept_description"), "name": r.get("name"), "category": r.get("category")}
            for r in rules
            if str(r.get("match_mode", "")).lower() == "concept" and r.get("enabled", True)
        ]
        payload = raw_jd.strip() + "::" + json.dumps(semantic_subset, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def get_cached_extraction(cache_key: str) -> Optional[Any]:
        return _TELEMETRY_EXTRACTION_CACHE.get(cache_key)

    @staticmethod
    def set_cached_extraction(cache_key: str, value: Any) -> None:
        _TELEMETRY_EXTRACTION_CACHE[cache_key] = value

    @classmethod
    def build_semantic_prompt_section(cls, rules: List[TelemetryRule]) -> str:
        """
        Formats active semantic / conceptual rules for the LLM prompt.
        If no semantic rules exist, returns an empty string (0 extra LLM tokens).
        """
        semantic_rules = [r for r in rules if r.enabled and (r.match_mode or "").lower() == "concept"]
        if not semantic_rules:
            return ""

        log_telemetry(f"Evaluating {len(semantic_rules)} semantic rules via LLM.")
        lines = []
        for idx, r in enumerate(semantic_rules, start=1):
            lines.append(
                f"{idx}. [{r.id}] {r.name} (Category: {r.category}, Severity: {r.severity})\n"
                f"   - Target Condition/Concept: {r.concept_description}"
            )

        return (
            "\n\nCONFIGURABLE SEMANTIC TELEMETRY RULES:\n"
            "Evaluate the job post against each semantic rule below. If the conceptual condition is met,\n"
            "add a distinct infraction to 'telemetry_warnings' (for warnings/flags) or 'telemetry_benefits' (for benefits)\n"
            "in the format '[<Rule Name>]: <Concise rationale tied directly to the job description>'.\n"
            "Do NOT combine multiple violations; record each matching rule separately:\n"
            + "\n".join(lines)
        )

    @classmethod
    def parse_semantic_infractions(
        cls,
        llm_messages: List[str],
        semantic_rules: List[TelemetryRule]
    ) -> List[TelemetryFinding]:
        """
        Maps strings returned by LLM (e.g. '[Federal Scope]: ...') back to structured TelemetryFinding objects.
        """
        findings: List[TelemetryFinding] = []
        for msg in llm_messages:
            clean_msg = str(msg).strip()
            if not clean_msg:
                continue

            matched_rule: Optional[TelemetryRule] = None
            extracted_reason = clean_msg

            # Check if formatted as [Rule Name/ID]: Reason
            match = re.match(r'^(?:(?:FLAG|BENEFIT|WARN):\s*)?\[([^\]]+)\](?::\s*(.*))?$', clean_msg, re.IGNORECASE)
            if match:
                identifier = match.group(1).strip()
                extracted_reason = (match.group(2) or "").strip() or clean_msg

                # Find by id or name
                for r in semantic_rules:
                    if r.id.lower() == identifier.lower() or r.name.lower() == identifier.lower():
                        matched_rule = r
                        break

            # Fallback fuzzy match on rule name
            if not matched_rule:
                for r in semantic_rules:
                    if r.name.lower() in clean_msg.lower() or r.id.lower() in clean_msg.lower():
                        matched_rule = r
                        break

            if matched_rule:
                findings.append(TelemetryFinding(
                    rule_id=matched_rule.id,
                    rule_name=matched_rule.name,
                    category=matched_rule.category.lower(),
                    match_mode="concept",
                    matched_text=None,
                    reason=extracted_reason or matched_rule.explanation or "Semantic condition detected in posting.",
                    domain_category=matched_rule.domain_category
                ))
            else:
                # Generic fallback if rule couldn't be mapped directly
                is_flag = "FLAG" in clean_msg.upper()
                is_benefit = "BENEFIT" in clean_msg.upper()
                cat = "flag" if is_flag else ("benefit" if is_benefit else "warning")
                findings.append(TelemetryFinding(
                    rule_id=f"semantic-{uuid.uuid4().hex[:6]}",
                    rule_name=clean_msg.split(":")[0].replace("[", "").replace("]", "").strip(),
                    category=cat,
                    match_mode="concept",
                    matched_text=None,
                    reason=clean_msg,
                    domain_category="Scope"
                ))

        return findings
