import re
import json
import uuid
import hashlib
from copy import deepcopy
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
            # Legacy dictionaries may never have been saved with an ID. Keep reads
            # stable; canonical creation assigns a random ID before normalization.
            identity = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            data["id"] = f"warn-{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex[:12]}"

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
        original_category = data.get("category")
        raw_cat = str(original_category or "").strip().lower()
        raw_sev = str(data.get("severity", "")).strip().lower()

        if raw_cat in TELEMETRY_RULE_CATEGORIES:
            data["category"] = raw_cat
        else:
            data["category"] = raw_sev if raw_sev in TELEMETRY_RULE_CATEGORIES else "warning"

        if not data.get("domain_category") or str(data["domain_category"]).lower() in TELEMETRY_RULE_CATEGORIES:
            legacy_domain = original_category if raw_cat and raw_cat not in TELEMETRY_RULE_CATEGORIES else None
            default_domain = next((r["domain_category"] for r in DEFAULT_TELEMETRY_RULES if r["id"] == data["id"]), "Scope")
            data["domain_category"] = legacy_domain or default_domain

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
        Boundary-aware literal matching that excludes hyphenated word components.
        Uses lookarounds to correctly handle tokens with punctuation (e.g. 401(k), TS/SCI).
        Does NOT match arbitrary substrings (e.g. 'FAR' inside 'software' or 'farmer').
        """
        p_clean = pattern.strip()
        if not p_clean:
            return None
        flags = 0 if case_sensitive else re.IGNORECASE
        regex_pattern = r'(?<![\w\-\u2010\u2011])' + re.escape(p_clean) + r'(?![\w\-\u2010\u2011])'
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
        regex_pattern = r'(?<![\w\-\u2010\u2011])' + re.escape(p_clean) + r'(?![\w\-\u2010\u2011])'
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
    def split_display_findings(flags=(), warnings=(), benefits=()):
        """Keep new classifications explicit; recognize canonical legacy prefixes."""
        groups = ([], [], [])
        for default_index, items in enumerate((flags, warnings, benefits)):
            for item in items or []:
                if isinstance(item, dict):
                    item = TelemetryFinding(**item)
                if isinstance(item, TelemetryFinding):
                    index = {"flag": 0, "warning": 1, "benefit": 2}.get(item.category, default_index)
                    value = item.to_display_string()
                else:
                    value = str(item).strip()
                    index = default_index
                    if value.upper().startswith("FLAG:"):
                        index = 0
                    elif value.upper().startswith("BENEFIT:"):
                        index = 2
                if index == 1 and value in groups[0]:
                    continue
                if value and value not in groups[index]:
                    groups[index].append(value)
        return groups

    @classmethod
    def serialize_display_findings(cls, fit_eval) -> str:
        flags, warnings, benefits = cls.split_display_findings(
            fit_eval.telemetry_flags, fit_eval.telemetry_warnings, fit_eval.telemetry_benefits
        )
        return json.dumps({"version": 1, "flags": flags, "warnings": warnings, "benefits": benefits})

    @classmethod
    def load_display_findings(cls, stored, legacy_note=""):
        """Read the optional Sheets cell, or extract only canonical old signal strings."""
        try:
            data = json.loads(stored) if isinstance(stored, str) and stored else stored
            if isinstance(data, dict) and data.get("version") == 1:
                if all(isinstance(data.get(k, []), list) for k in ("flags", "warnings", "benefits")):
                    return cls.split_display_findings(data.get("flags", []), data.get("warnings", []), data.get("benefits", []))
        except (ValueError, TypeError):
            pass
        # Old Fit Warning cells combined reasoning with semicolon-separated findings.
        matches = re.findall(r"(?:FLAG:\s*|BENEFIT:\s*)?\[[^\]]+\]:\s*.*?(?=;\s*(?:(?:FLAG|BENEFIT):\s*)?\[|$)", str(legacy_note))
        return cls.split_display_findings([], matches, [])

    @classmethod
    def compute_cache_key(cls, raw_jd: str, rules: List[Dict[str, Any]]) -> str:
        """The cached payload includes every finding, so hash every active rule property."""
        active_rules = [cls.normalize_rule_dict(r) for r in rules if r.get("enabled", True)]
        serialized = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in active_rules)
        payload = json.dumps([raw_jd, serialized], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def get_cached_extraction(cache_key: str) -> Optional[Any]:
        return deepcopy(_TELEMETRY_EXTRACTION_CACHE.get(cache_key))

    @staticmethod
    def set_cached_extraction(cache_key: str, value: Any) -> None:
        _TELEMETRY_EXTRACTION_CACHE[cache_key] = deepcopy(value)

    @classmethod
    def build_semantic_prompt_section(cls, rules: List[TelemetryRule]) -> str:
        """
        Formats active semantic / conceptual rules for the LLM prompt.
        If no semantic rules exist, returns an empty string (0 extra LLM tokens).
        """
        semantic_rules = [r for r in rules if r.enabled and (r.match_mode or "").lower() == "concept" and cls.validate_rule(r)[0]]
        if not semantic_rules:
            return ""

        log_telemetry(f"Evaluating {len(semantic_rules)} semantic rules via LLM.")
        lines = []
        for idx, r in enumerate(semantic_rules, start=1):
            lines.append(
                f"{idx}. [{r.id}] {r.name} (Category: {r.category}, Domain: {r.domain_category})\n"
                f"   - Target Condition/Concept: {r.concept_description}\n"
                f"   - Supporting terms/examples: {json.dumps(r.patterns, ensure_ascii=False)}"
            )

        return (
            "\n\nCONFIGURABLE SEMANTIC TELEMETRY RULES:\n"
            "You MUST evaluate EVERY semantic rule below independently against the ENTIRE job post.\n"
            "Treat the rules as an exhaustive checklist: consider rule 1, then rule 2, and continue through the final rule.\n"
            "Do not stop evaluating after finding several matches. Multiple rules may match the same passage or overlapping evidence.\n"
            "For each rule, decide whether its Target Condition/Concept is satisfied by the job post.\n"
            "Return every configured rule whose condition is satisfied. Omit rules whose conditions are not satisfied.\n"
            "add a distinct finding to 'telemetry_flags', 'telemetry_warnings', or 'telemetry_benefits' according to its configured category.\n"
            "Each array item MUST be a string in the format '[rule-id]: rationale'. Use the exact stable rule ID supplied below.\n"
            "Do not substitute the display name for the identifier. Do not return bare IDs: include brackets, a colon, and one short rationale grounded in the job description.\n"
            f"Format example using a configured ID: '[{semantic_rules[0].id}]: Brief evidence from the job description.'\n"
            "If a rule does not match, omit it. Do not create new identifiers or signal types.\n"
            "Return findings ONLY for these active configured rules. Never invent rules or classifications.\n"
            "Supporting terms are examples and hints, NOT automatic triggers. Their mere presence is not sufficient.\n"
            "Evaluate the complete job-post context against the target condition, including all qualifiers and exclusions.\n"
            "Supporting terms/examples are illustrative only. A rule may match even when NONE of its supporting terms appears verbatim, if the job post clearly satisfies the Target Condition/Concept.\n"
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
        semantic_rules = [r for r in semantic_rules if r.enabled and r.match_mode == "concept" and cls.validate_rule(r)[0]]
        rejected = 0
        for msg in llm_messages:
            clean_msg = str(msg).strip()
            if not clean_msg:
                continue

            matched_rule: Optional[TelemetryRule] = None
            extracted_reason = ""
            identifier = clean_msg

            # Check if formatted as [Rule Name/ID]: Reason
            match = re.match(r'^(?:(?:FLAG|BENEFIT|WARN):\s*)?\[([^\]]+)\](?::\s*(.*))?$', clean_msg, re.IGNORECASE | re.DOTALL)
            if match:
                identifier = match.group(1).strip()
                extracted_reason = " ".join((match.group(2) or "").split())

                # IDs take precedence; duplicate names cannot identify a rule safely.
                matches = [r for r in semantic_rules if r.id.casefold() == identifier.casefold()]
                if not matches:
                    matches = [r for r in semantic_rules if r.name.casefold() == identifier.casefold()]
                if len(matches) == 1:
                    matched_rule = matches[0]

            # Legacy unbracketed output must still use an exact canonical identifier.
            if not matched_rule and not match:
                identifier, sep, reason = clean_msg.partition(":")
                matches = [r for r in semantic_rules if identifier.strip().casefold() == r.id.casefold()]
                if not matches and sep:
                    matches = [r for r in semantic_rules if identifier.strip().casefold() == r.name.casefold()]
                if len(matches) == 1:
                    matched_rule = matches[0]
                    extracted_reason = " ".join(reason.split())

            if matched_rule:
                if any(f.rule_id == matched_rule.id for f in findings):
                    continue
                findings.append(TelemetryFinding(
                    rule_id=matched_rule.id,
                    rule_name=matched_rule.name,
                    category=matched_rule.category.lower(),
                    match_mode="concept",
                    matched_text=None,
                    reason=extracted_reason or "Model matched this configured rule but supplied no rationale; verify against the job description.",
                    domain_category=matched_rule.domain_category
                ))
            else:
                rejected += 1
                safe_identifier = " ".join(identifier.split())[:100]
                log_warn(f"Discarding semantic finding: identifier {safe_identifier!r} does not resolve to an active configured Concept rule.")

        if llm_messages:
            log_telemetry(f"Semantic mapping: returned={len(llm_messages)}, accepted={len(findings)}, rejected={rejected}.")
        return findings
