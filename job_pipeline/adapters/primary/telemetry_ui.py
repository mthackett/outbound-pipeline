"""Shared Job Signals controls and presentation; persistence stays in the config service."""
import re

import streamlit as st

from job_pipeline.domain.models import TELEMETRY_DOMAIN_CATEGORIES
from job_pipeline.domain.services import PipelineConfigService
from job_pipeline.domain.telemetry_service import TelemetryService


MATCH_TYPES = ["Direct Match", "Concept (LLM)", "Regex (Advanced)"]


def match_type_label(mode):
    return {"concept": MATCH_TYPES[1], "regex": MATCH_TYPES[2]}.get(mode, MATCH_TYPES[0])


def rule_editor_fields(existing, name, classification, match_type, domain, patterns, condition, case_sensitive, enabled):
    """Return only edited fields so hidden and unknown legacy metadata survives."""
    mode = {MATCH_TYPES[0]: "phrase", MATCH_TYPES[1]: "concept", MATCH_TYPES[2]: "regex"}[match_type]
    if match_type == MATCH_TYPES[0] and existing.get("match_mode") in ("token", "phrase"):
        mode = existing["match_mode"]
    fields = dict(name=name.strip(), category=classification, match_mode=mode,
                  domain_category=domain, patterns=patterns, enabled=enabled)
    # Keep independent legacy keywords if the supporting terms were not changed.
    if patterns != existing.get("patterns", existing.get("keywords", [])):
        fields["keywords"] = patterns
    if mode == "concept":
        fields["concept_description"] = condition.strip()
    else:
        fields["case_sensitive"] = case_sensitive
    return fields


def render_rule_editor(key, existing=None):
    existing = existing or {}
    name = st.text_input("Rule Display Name", value=existing.get("name", ""), key=f"{key}_name")
    categories = ["warning", "flag", "benefit"]
    category = st.selectbox("Rule Classification", categories,
                            index=categories.index(existing.get("category", "warning")),
                            format_func=lambda v: {"warning": "Warning", "flag": "Flag", "benefit": "Positive Signal"}[v],
                            key=f"{key}_category")
    mode_col, domain_col = st.columns(2)
    with mode_col:
        match_type = st.selectbox("Match Type", MATCH_TYPES,
                                  index=MATCH_TYPES.index(match_type_label(existing.get("match_mode", "concept"))),
                                  key=f"{key}_mode")
    with domain_col:
        domains = list(TELEMETRY_DOMAIN_CATEGORIES)
        domain = existing.get("domain_category", "Scope")
        if domain not in domains:
            domains.append(domain)
        domain = st.selectbox("Domain Category", domains, index=domains.index(domain), key=f"{key}_domain")

    condition = existing.get("concept_description", "")
    case_sensitive = existing.get("case_sensitive", False)
    if match_type == "Concept (LLM)":
        condition = st.text_area("Condition to detect", value=condition, key=f"{key}_condition",
                                 help="Required. Describe the condition and when it should not apply.")
        pattern_label = "Supporting terms or examples (optional)"
        pattern_help = "One per line. These are context hints, not automatic triggers."
    elif match_type == "Regex (Advanced)":
        pattern_label = "Regex pattern(s)"
        pattern_help = "Advanced literal-pattern matching using regular expressions. One pattern per line; commas stay inside patterns."
    else:
        pattern_label = "Words or phrases to match"
        pattern_help = "One per line. Matches complete literal terms, including punctuation; excludes parts of hyphenated compounds."
    patterns_raw = st.text_area(pattern_label, value="\n".join(existing.get("patterns") or existing.get("keywords") or []),
                                help=pattern_help, key=f"{key}_patterns")
    if match_type != "Concept (LLM)":
        case_sensitive = st.checkbox("Case Sensitive", value=case_sensitive, key=f"{key}_case")
    enabled = st.checkbox("Enabled", value=existing.get("enabled", True), key=f"{key}_enabled")
    if st.button("Save Job Signal Rule", key=f"{key}_save"):
        fields = rule_editor_fields(existing, name, category, match_type, domain,
                                    [p.strip() for p in patterns_raw.splitlines() if p.strip()],
                                    condition, case_sensitive, enabled)
        try:
            if existing:
                PipelineConfigService.update_telemetry_rule(existing["id"], fields)
            else:
                PipelineConfigService.add_telemetry_rule(fields)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            return False
        st.success("Job Signal rule saved.")
        return True
    return False


def render_telemetry_warnings_manager(key_prefix="sb"):
    rules = PipelineConfigService.get_telemetry_rules()
    active = sum(r.get("enabled", True) for r in rules)
    st.caption("Create rules for conditions you want More Outbound to watch for in job postings.")
    st.caption(f"{active}/{len(rules)} active")
    revision_key = "telemetry_rule_revision"
    revision = st.session_state.get(revision_key, 0)
    with st.expander("Add Job Signal Rule"):
        if render_rule_editor(f"{key_prefix}_new_{revision}"):
            st.session_state[revision_key] = revision + 1
            st.rerun()
    st.markdown("###### Job Signal Rules")
    for rule in rules:
        rid = rule["id"]
        st.write(rule["name"])
        category = {"flag": "Flag", "warning": "Warning", "benefit": "Positive Signal"}[rule["category"]]
        st.caption(f"{category} · {match_type_label(rule['match_mode'])} · {rule['domain_category']} · "
                   + ("Enabled" if rule["enabled"] else "Disabled"))
        with st.expander(f"Edit {rule['name']}"):
            if render_rule_editor(f"{key_prefix}_{rid}_{revision}", rule):
                st.session_state[revision_key] = revision + 1
                st.rerun()
        if st.button("Delete", key=f"{key_prefix}_delete_{rid}"):
            PipelineConfigService.remove_telemetry_rule(rid)
            st.rerun()
    if st.button("Reset to Default Rules", key=f"{key_prefix}_reset"):
        PipelineConfigService.reset_default_telemetry_rules()
        st.session_state[revision_key] = revision + 1
        st.rerun()


def render_job_signals(flags=(), warnings=(), benefits=()):
    groups = TelemetryService.split_display_findings(flags, warnings, benefits)
    if not any(groups):
        return
    st.markdown("#### Job Signals")
    for title, render, findings in zip(("Flags", "Warnings", "Positive Signals"),
                                       (st.error, st.warning, st.success), groups):
        if findings:
            lines = []
            for finding in findings:
                clean = re.sub(r"^(?:FLAG|BENEFIT|WARN):\s*", "", finding, flags=re.IGNORECASE)
                match = re.match(r"^\[([^\]]+)\]:\s*(.*)$", clean, re.DOTALL)
                if match:
                    name = match[1]
                    body = match[2]
                    if " - Evidence: " in body:
                        reason_part, _, evidence_part = body.partition(" - Evidence: ")
                        clean = f"**{name}**  \n{reason_part}  \n**Evidence:** {evidence_part}"
                    else:
                        clean = f"**{name}**  \n{body}"
                lines.append(clean)
            render(f"**{title}**\n\n" + "\n\n".join(lines))
