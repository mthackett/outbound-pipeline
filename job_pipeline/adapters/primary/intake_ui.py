"""Shared intake UI component supporting Job Post ingestion and Inbound Lead creation."""

import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import streamlit as st

from job_pipeline.domain.models import (
    JobPosting, FitEvaluation, TargetPayBounds,
    DEFAULT_APPLICATION_SOURCES, DEFAULT_PRIORITIES,
    APPLICATION_CATEGORIES, CATEGORY_ICONS,
    SCREENING_CATEGORIES, SCREENING_ARCHETYPES,
    ScreeningQA
)
from job_pipeline.domain.services import (
    PipelineConfigService, ApplicationGuardrailService, JobQualificationService
)
from job_pipeline.domain.screening_intelligence import ScreeningIntelligenceService
from job_pipeline.domain.telemetry_service import TelemetryService
from job_pipeline.logger import log_action, log_drive, log_sheets, log_success, log_warn


def render_shared_intake(
    storage_adapter,
    drive_adapter,
    llm_adapter,
    resume_repo,
    demo_mode: bool = False,
    view_context: str = "ingest"
):
    """
    Renders the shared intake interface for Job Post (outbound) and Inbound Lead.
    Can be mounted in 'Ingest & Apply' (view_context='ingest') or inside '+ Add Opportunity' in Pipeline Tracker.
    """
    pfx = "" if view_context == "ingest" else f"{view_context}_"

    # Native segmented control with fallback to radio if unavailable
    mode_options = ["Job Post", "Inbound Lead"]
    try:
        selected_mode = st.segmented_control(
            "Intake Mode",
            mode_options,
            default="Job Post",
            key=f"{pfx}mode_segmented",
            label_visibility="collapsed"
        )
        if not selected_mode:
            selected_mode = "Job Post"
    except (AttributeError, TypeError):
        selected_mode = st.radio(
            "Intake Mode",
            mode_options,
            index=0,
            horizontal=True,
            key=f"{pfx}mode_radio",
            label_visibility="collapsed"
        )

    if selected_mode == "Inbound Lead":
        _render_inbound_lead_form(storage_adapter, llm_adapter, pfx)
    else:
        _render_job_post_form(
            storage_adapter=storage_adapter,
            drive_adapter=drive_adapter,
            llm_adapter=llm_adapter,
            resume_repo=resume_repo,
            demo_mode=demo_mode,
            pfx=pfx,
            view_context=view_context
        )


def _render_inbound_lead_form(storage_adapter, llm_adapter, pfx: str):
    """Renders the lightweight Inbound Lead creation form."""
    st.markdown("##### 📥 Log Inbound Lead")
    st.caption("Quickly capture recruiter outreaches, agency introductions, and network leads without JD parsing or heavy document generation.")

    col1, col2 = st.columns(2)
    with col1:
        contact_name = st.text_input(
            "Contact Name",
            placeholder="e.g. Sarah Jenkins (Recruiter / HM)",
            key=f"{pfx}inbound_contact",
            autocomplete="off"
        )
    with col2:
        company_name = st.text_input(
            "Company",
            placeholder="e.g. Stripe, Acme Corp",
            key=f"{pfx}inbound_company",
            autocomplete="off"
        )

    job_title = st.text_input(
        "Job Title (Optional)",
        placeholder="e.g. Senior RevOps Analyst",
        key=f"{pfx}inbound_title",
        autocomplete="off"
    )

    inbound_jd = st.text_area(
        "Job Description / Outreach Message (Optional)",
        placeholder="Paste outreach message, role scope, or recruiter email text...",
        height=120,
        key=f"{pfx}inbound_jd"
    )

    # Optional lightweight job signals extraction if JD is provided
    if inbound_jd.strip() and len(inbound_jd.strip()) >= 50:
        with st.expander("🔍 Optional: Extract Job Signals from Outreach Text", expanded=False):
            st.caption("Analyze compensation, role signals, or red flags without triggering document exports.")
            if st.button("Run Quick Signals Scan", key=f"{pfx}inbound_scan_btn"):
                if hasattr(llm_adapter, "evaluate_job_signals"):
                    warning_rules = PipelineConfigService.get_active_telemetry_rules()
                    s_flags, s_warnings, s_benefits = llm_adapter.evaluate_job_signals(inbound_jd.strip(), rules=warning_rules)
                    st.session_state[f"{pfx}inbound_signals"] = (s_flags, s_warnings, s_benefits)
                    st.rerun()

            if st.session_state.get(f"{pfx}inbound_signals"):
                flags, warnings, benefits = st.session_state[f"{pfx}inbound_signals"]
                if flags:
                    st.warning("⚠️ Flags: " + ", ".join(flags))
                if warnings:
                    st.info("ℹ️ Notes: " + ", ".join(warnings))
                if benefits:
                    st.success("✅ Positive Signals: " + ", ".join(benefits))

    inbound_notes = st.text_area(
        "Initial Notes / Context (Optional)",
        placeholder="e.g. Reached out via LinkedIn InMail; hiring manager is VP of GTM Ops; initial call set for next Tuesday.",
        height=80,
        key=f"{pfx}inbound_notes"
    )

    if st.button("📥 Save Inbound Lead", type="primary", use_container_width=True, key=f"{pfx}btn_save_inbound"):
        clean_contact = contact_name.strip()
        clean_company = company_name.strip()
        clean_title = job_title.strip()

        # Validation: Require at least one of Contact or Company
        if not clean_contact and not clean_company:
            st.error("Please provide at least a Contact Name or Company Name to log this inbound lead.")
            return

        opp_id = str(uuid.uuid4())
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        job_posting = JobPosting(
            opportunity_id=opp_id,
            company_name=clean_company,
            job_title=clean_title,
            contact_name=clean_contact,
            opportunity_source="Inbound",
            raw_description=inbound_jd.strip(),
            notes=inbound_notes.strip(),
            stage_history=[{"stage": "New Lead", "entered_at": now_iso}],
            category="Target",
            role_intelligence_status="Not Generated"
        )

        # Preserve raw JD text locally if supplied so future deep processing or RI has it available
        if inbound_jd.strip():
            try:
                raw_jd_dir = Path("output_reports") / uuid.uuid5(uuid.NAMESPACE_URL, opp_id).hex
                raw_jd_dir.mkdir(parents=True, exist_ok=True)
                (raw_jd_dir / "Raw_JD.txt").write_text(inbound_jd.strip(), encoding="utf-8")
            except Exception:
                pass

        try:
            saved = storage_adapter.save_opportunity(job_posting, None)
            if saved:
                # Invalidate CRM cache so the new opportunity appears immediately
                st.session_state.pop("crm_cached_opportunities", None)
                lead_display = clean_company or clean_contact
                st.session_state["crm_flash_message"] = (
                    f"Inbound lead '{lead_display}' logged successfully!"
                )
                log_success(f"Inbound lead created for '{lead_display}' ({opp_id})")
                st.rerun()
            else:
                st.error("Could not save inbound lead. Please verify storage connection and retry.")
        except Exception as err:
            st.error(f"Error saving inbound lead: {err}")


def _render_job_post_form(
    storage_adapter,
    drive_adapter,
    llm_adapter,
    resume_repo,
    demo_mode: bool,
    pfx: str,
    view_context: str
):
    """Renders the outbound Job Post intake form with reorganized Advanced Options."""
    counter_key = "intake_counter" if view_context == "ingest" else f"{pfx}counter"
    if counter_key not in st.session_state:
        st.session_state[counter_key] = 0
    cur_idx = st.session_state[counter_key]

    st.markdown("##### 📄 Process Job Description")
    st.caption("Paste a job description to screen fit, extract role details, and generate application artifacts.")

    jd_text_input = st.text_area(
        "Job Description Text",
        height=180,
        placeholder="Paste full job description text here...",
        label_visibility="collapsed",
        key=f"{pfx}jd_text_input_{cur_idx}"
    )

    with st.expander("Application Notes", expanded=False):
        st.caption("Add unstructured notes, referral contacts, or outreach angles.")
        manual_notes = st.text_area(
            "Application Notes",
            height=80,
            placeholder="e.g. Referral from Sarah; emphasizes ARR modeling...",
            key=f"{pfx}ov_notes_{cur_idx}",
            label_visibility="collapsed"
        )

    # Reorganized Advanced Options in 3 logical groups
    with st.expander("Advanced Options", expanded=False):
        st.markdown("###### 1. Role & Classification")
        col_rc1, col_rc2 = st.columns(2)
        with col_rc1:
            manual_company = st.text_input("Override Company Name", placeholder="Auto-detect from text", key=f"{pfx}ov_comp_{cur_idx}", autocomplete="off")
            manual_family = st.selectbox(
                "Role Family",
                ["Auto-Detect", "revenue_operations", "revenue_systems", "business_analytics", "gtm_engineering", "solutions_implementation"],
                index=0,
                key=f"{pfx}ov_family_{cur_idx}"
            )
        with col_rc2:
            manual_title = st.text_input("Override Job Title", placeholder="Auto-detect from text", key=f"{pfx}ov_title_{cur_idx}", autocomplete="off")
            manual_category = st.selectbox(
                "Strategic Category",
                ["Target", "Stretch", "Opportunistic", "Practice", "Fallback"],
                index=0,
                key=f"{pfx}ov_cat_{cur_idx}",
                help="Defaults to Target."
            )

        st.markdown("---")
        st.markdown("###### 2. Source & Priority")
        pipeline_cfg = PipelineConfigService.load_config()
        sources_list = ["Not specified"] + [s for s in pipeline_cfg.get("sources", DEFAULT_APPLICATION_SOURCES) if s != "Not specified"]
        priorities_list = ["Not specified"] + [p for p in pipeline_cfg.get("priorities", DEFAULT_PRIORITIES) if p != "Not specified"]

        col_sp1, col_sp2 = st.columns(2)
        with col_sp1:
            manual_applied_via = st.selectbox(
                "Applied Via",
                sources_list,
                index=0,
                key=f"{pfx}ov_src_{cur_idx}",
                help="Platform or source. Defaults to Not specified."
            )
            manual_url = st.text_input("Job Source URL", placeholder="https://linkedin.com/jobs/...", key=f"{pfx}ov_url_{cur_idx}", autocomplete="off")
        with col_sp2:
            manual_priority = st.selectbox(
                "Priority",
                priorities_list,
                index=0,
                key=f"{pfx}ov_pri_{cur_idx}",
                help="Priority tier. Defaults to Not specified."
            )
            st.caption("Opportunity Source: **Outbound** (assigned automatically for Job Post mode)")

        st.markdown("---")
        st.markdown("###### 3. Compensation & Employment")
        col_ce1, col_ce2, col_ce3 = st.columns(3)
        with col_ce1:
            manual_salary_expectation = st.text_input(
                "Salary Expectation",
                placeholder="e.g. $140k or $75/hr",
                key=f"{pfx}ov_sal_exp_{cur_idx}",
                help="Your target compensation."
            )
            manual_arrangement = st.selectbox(
                "Employment Arrangement",
                ["Auto-Detect", "Employee", "Contract"],
                index=0,
                key=f"{pfx}ov_arr_{cur_idx}"
            )
        with col_ce2:
            manual_min_pay = st.number_input("Override Min Pay ($ / hr or yr)", value=0, step=5, key=f"{pfx}ov_min_{cur_idx}")
            manual_pay_basis = st.selectbox(
                "Pay Basis",
                ["Auto-Detect", "Annual", "Hourly"],
                index=0,
                key=f"{pfx}ov_pb_{cur_idx}"
            )
        with col_ce3:
            manual_max_pay = st.number_input("Override Max Pay ($ / hr or yr)", value=0, step=5, key=f"{pfx}ov_max_{cur_idx}")
            manual_worker_class = st.selectbox(
                "Worker Classification",
                ["Auto-Detect", "Not Specified", "W2", "1099", "C2C"],
                index=0,
                key=f"{pfx}ov_wc_{cur_idx}"
            )

        col_ce4, col_ce5 = st.columns(2)
        with col_ce4:
            manual_duration = st.text_input(
                "Contract Duration",
                placeholder="e.g. 6 months",
                key=f"{pfx}ov_dur_{cur_idx}",
                autocomplete="off"
            )
        with col_ce5:
            manual_agency_client = st.text_input(
                "Staffing Agency / Client Company",
                placeholder="e.g. Apex Systems supporting Braze",
                key=f"{pfx}ov_agency_{cur_idx}",
                autocomplete="off"
            )

    # Screening Q&A expander
    with st.expander("Screening Questions & Answers", expanded=False):
        st.caption("Optionally record questions and answers requested on this application. When provided, they are saved into a dedicated 'Screening Questions' Google Doc in your Drive folder and logged into your reusable master Q&A library.")
        qa_count_key = "num_screening_qa" if view_context == "ingest" else f"{pfx}num_screening_qa"
        if qa_count_key not in st.session_state:
            st.session_state[qa_count_key] = 0

        col_qa1, col_qa2, _ = st.columns([1, 1, 3])
        with col_qa1:
            if st.button("➕ Add Question", key=f"{pfx}btn_add_qa"):
                st.session_state[qa_count_key] += 1
                st.rerun()
        with col_qa2:
            if st.session_state[qa_count_key] > 0:
                if st.button("➖ Remove Last", key=f"{pfx}btn_rm_qa"):
                    rem_idx = st.session_state[qa_count_key] - 1
                    st.session_state.pop(f"{pfx}sq_sim_matches_{rem_idx}", None)
                    st.session_state.pop(f"{pfx}sq_sim_query_{rem_idx}", None)
                    st.session_state[qa_count_key] -= 1
                    st.rerun()

        # Load historical screening QA for similarity recall (cached in session state)
        if "_cached_historical_qa" not in st.session_state:
            st.session_state._cached_historical_qa = (
                storage_adapter.fetch_screening_qa()
                if (storage_adapter and getattr(storage_adapter, "is_connected", False))
                else []
            )
        historical_qa = st.session_state._cached_historical_qa

        screening_inputs: List[ScreeningQA] = []
        for i in range(st.session_state[qa_count_key]):
            st.markdown("---")
            st.markdown(f"**Screening Question {i + 1}**")
            cq1, cq2 = st.columns([3, 1])
            with cq1:
                q_text = st.text_input(
                    "Question Prompt",
                    key=f"{pfx}sq_q_{i}",
                    placeholder="e.g. Describe your experience with Salesforce & dbt."
                )
            with cq2:
                q_cat = st.selectbox("Category", SCREENING_CATEGORIES, key=f"{pfx}sq_cat_{i}")

            # Screening Question Intelligence: Archetype & Recall
            q_arch = "GENERAL"
            q_signals = []
            if q_text and len(q_text.strip()) >= 5:
                q_arch = ScreeningIntelligenceService.classify_archetype(q_text)
                q_signals = ScreeningIntelligenceService.extract_competency_signals(q_text)

                c_info1, c_info2 = st.columns([2, 1])
                with c_info1:
                    if q_signals:
                        pills = " ".join([
                            f'<span class="badge-pill" style="background:#1E3A8A; color:#BFDBFE; font-size:0.75rem;">{s}</span>'
                            for s in q_signals
                        ])
                        st.markdown(f"<b>Competencies Detected:</b> {pills}", unsafe_allow_html=True)
                with c_info2:
                    st.caption(f"Archetype: `{SCREENING_ARCHETYPES.get(q_arch, q_arch)}`")

            # On-demand prior-answer similarity search
            col_sim_action, col_sim_empty = st.columns([1.5, 2.5])
            with col_sim_action:
                btn_find_sim = st.button(
                    "🔍 Find Similar Answers",
                    key=f"{pfx}btn_find_sim_{i}",
                    help="Search historical Q&A for similar past questions and answers"
                )

            if btn_find_sim:
                if not q_text or len(q_text.strip()) < 3:
                    st.warning("Please enter a question prompt to search past answers.")
                    st.session_state[f"{pfx}sq_sim_matches_{i}"] = None
                else:
                    matches = ScreeningIntelligenceService.find_similar_questions(q_text, historical_qa, threshold=0.35)
                    st.session_state[f"{pfx}sq_sim_matches_{i}"] = matches
                    st.session_state[f"{pfx}sq_sim_query_{i}"] = q_text.strip()

            saved_matches = st.session_state.get(f"{pfx}sq_sim_matches_{i}")
            if saved_matches is not None:
                # Invalidate if user modified question prompt
                if q_text.strip() != st.session_state.get(f"{pfx}sq_sim_query_{i}", ""):
                    st.session_state[f"{pfx}sq_sim_matches_{i}"] = None
                    saved_matches = None

            if saved_matches:
                top_m = saved_matches[0]
                c_sim1, c_sim2 = st.columns([5, 1])
                with c_sim1:
                    st.info(
                        f"💡 **Similar Past Question Found ({int(top_m.similarity_score * 100)}% match)**\n\n"
                        f"*Prior Question:* \"{top_m.matched_question}\" ({top_m.company_name or 'Past Role'})\n\n"
                        f"**Prior Answer:** {top_m.matched_answer}"
                    )
                with c_sim2:
                    if st.button("✖ Close", key=f"{pfx}btn_close_sim_{i}", help="Dismiss match"):
                        st.session_state[f"{pfx}sq_sim_matches_{i}"] = None
                        st.rerun()

                def _make_recall_callback(idx=i, ans_val=top_m.matched_answer, arch=top_m.archetype):
                    def _cb():
                        st.session_state[f"{pfx}sq_a_{idx}"] = ans_val
                        if arch == "COMPENSATION":
                            st.session_state[f"{pfx}sq_cat_{idx}"] = "Salary"
                        elif arch == "TECHNICAL_STACK":
                            st.session_state[f"{pfx}sq_cat_{idx}"] = "Technical"
                        elif arch == "EXPERIENCE_DOMAIN":
                            st.session_state[f"{pfx}sq_cat_{idx}"] = "Experience"
                        elif arch == "QUESTIONS_FOR_COMPANY":
                            st.session_state[f"{pfx}sq_cat_{idx}"] = "Questions for Company"
                        st.session_state[f"{pfx}sq_sim_matches_{idx}"] = None
                    return _cb

                st.button(
                    f"📋 Use Prior Answer for Question {i + 1}",
                    key=f"{pfx}btn_recall_qa_{i}",
                    on_click=_make_recall_callback()
                )
            elif saved_matches == []:
                c_none1, c_none2 = st.columns([5, 1])
                with c_none1:
                    st.caption(f"ℹ️ No similar questions found in past records for *\"{st.session_state.get(f'{pfx}sq_sim_query_{i}', '')}\"*.")
                with c_none2:
                    if st.button("✖ Close", key=f"{pfx}btn_close_none_{i}"):
                        st.session_state[f"{pfx}sq_sim_matches_{i}"] = None
                        st.rerun()

            ca1, ca2 = st.columns([4, 1])
            with ca1:
                ans_text = st.text_area(
                    "Your Answer",
                    key=f"{pfx}sq_a_{i}",
                    height=85,
                    placeholder="Enter your response for this application..."
                )
            with ca2:
                ai_draft_btn = st.button(
                    "✨ Draft with AI",
                    key=f"{pfx}sq_ai_{i}",
                    help="Draft a tailored answer using your profile & the JD"
                )
                if ai_draft_btn:
                    if not q_text:
                        st.warning("Please enter a question prompt first.")
                    else:
                        with st.spinner("Drafting answer with AI..."):
                            client = getattr(llm_adapter, "client", None)
                            cand_prof = st.session_state.get("profile")
                            prof_name = getattr(cand_prof, "candidate_name", "the candidate") if cand_prof else "the candidate"
                            strengths = ", ".join(getattr(cand_prof, "core_strengths", [])) if cand_prof else ""
                            if not demo_mode and client:
                                try:
                                    draft_prompt = (
                                        f"You are helping candidate {prof_name} answer a screening question.\n"
                                        f"Core strengths: {strengths}.\n"
                                        f"Target role: {manual_title or 'RevOps / Analytics professional'}.\n"
                                        f"Target company: {manual_company or 'Tech Company'}.\n"
                                        f"Job Description excerpt: {jd_text_input[:800] if jd_text_input else 'N/A'}\n"
                                        f"Screening Question: {q_text}\n\n"
                                        f"Write a concise, high-impact, professional application answer (2-4 sentences or tight bullet points). Make it ATS-friendly and confident."
                                    )
                                    resp = client.chat.completions.create(
                                        model="gpt-4o",
                                        messages=[{"role": "user", "content": draft_prompt}],
                                        temperature=0.4,
                                        max_tokens=250
                                    )
                                    st.session_state[f"{pfx}sq_a_{i}"] = resp.choices[0].message.content.strip()
                                    st.rerun()
                                except Exception as d_err:
                                    st.error(f"AI draft notice: {d_err}")
                            else:
                                st.session_state[f"{pfx}sq_a_{i}"] = (
                                    f"Experienced professional specializing in {strengths or 'Revenue Operations, analytics, and systems architecture'}. "
                                    f"Demonstrated track record of delivering measurable pipeline efficiency and actionable BI insights aligned with this role."
                                )
                                st.rerun()

            if q_text and ans_text:
                screening_inputs.append(ScreeningQA(question=q_text, answer=ans_text, category=q_cat))

    # Clean mappings for defaults
    clean_applied_via = "" if manual_applied_via == "Not specified" else manual_applied_via
    clean_priority = "" if manual_priority == "Not specified" else manual_priority
    clean_arrangement = "Employee" if manual_arrangement == "Auto-Detect" else manual_arrangement
    clean_family = "revenue_operations" if manual_family == "Auto-Detect" else manual_family
    clean_pay_basis = "Annual" if manual_pay_basis == "Auto-Detect" else manual_pay_basis
    clean_worker_class = "" if manual_worker_class in ("Auto-Detect", "Not Specified") else manual_worker_class

    # Process Button
    if st.button("⚡ Process Job", type="primary", use_container_width=True, key=f"{pfx}btn_process"):
        if not jd_text_input or len(jd_text_input.strip()) < 20:
            st.error("Please paste a valid job description (at least 20 characters).")
            return

        with st.spinner("Extracting role telemetry, screening fit, and generating application records..."):
            all_opps = storage_adapter.fetch_all_opportunities() if (storage_adapter and storage_adapter.is_connected) else []
            opp_id = str(uuid.uuid4())

            # 1. Telemetry extraction (AI or fallback)
            telemetry = None
            t_ext_start = time.perf_counter()
            warning_rules = PipelineConfigService.get_active_telemetry_rules()
            if hasattr(llm_adapter, "extract_job_telemetry"):
                try:
                    telemetry = llm_adapter.extract_job_telemetry(
                        jd_text_input,
                        warning_rules=warning_rules
                    )
                    tokens = getattr(llm_adapter, "last_telemetry_tokens", 0)
                    t_ext_elapsed = time.perf_counter() - t_ext_start
                    log_action(f"Step 1/5 [Metadata & Telemetry Extraction]: Completed in {t_ext_elapsed:.2f}s ({tokens} tokens)")
                except Exception as t_err:
                    log_warn(f"Step 1/5 [Metadata & Telemetry Extraction]: Failed: {t_err}")
                    st.error(f"Metadata extraction failed: {t_err}")
                    return
            else:
                log_action("Step 1/5 [Metadata & Telemetry Extraction]: Skipped (adapter lacks telemetry extraction)")

            # Typed schema validation and direct attribute access
            if telemetry is not None:
                if not hasattr(telemetry, "requirements") or telemetry.requirements is None:
                    err_msg = "Invalid extraction payload: missing 'requirements' schema field."
                    log_warn(f"Step 1/5 [Metadata & Telemetry Extraction]: Failed: {err_msg}")
                    st.error(err_msg)
                    return
                reqs = telemetry.requirements

                # Direct typed access for required JobExtractionPayload fields
                extracted_company = telemetry.company_name
                extracted_title = telemetry.job_title
                extracted_family = telemetry.title_family
                extracted_url = telemetry.source_url

                # Direct typed access for required and optional JobRequirementsSchema fields
                extracted_min = reqs.salary_min
                extracted_max = reqs.salary_max
                extracted_arr = reqs.employment_arrangement
                extracted_pb = reqs.pay_basis
                extracted_wc = reqs.worker_classification
                extracted_dur = reqs.contract_length_raw
                extracted_months = reqs.contract_length_months
                extracted_weeks = reqs.contract_length_weeks
                extracted_hours = reqs.expected_hours_per_week
                extracted_ext = reqs.extension_possible
                extracted_fte = reqs.fte_conversion_possible
                extracted_agency = reqs.staffing_agency
                extracted_client = reqs.client_company
                req_skills = reqs.required_tech_stack
                pref_skills = reqs.preferred_tech_stack
                pain_points = reqs.core_pain_points or ""
                is_remote = reqs.is_remote
                t_warnings = reqs.telemetry_warnings
                t_flags = reqs.telemetry_flags
                t_benefits = reqs.telemetry_benefits
            else:
                extracted_company = ""
                extracted_title = ""
                extracted_family = "revenue_operations"
                extracted_url = ""
                extracted_min = None
                extracted_max = None
                extracted_arr = None
                extracted_pb = None
                extracted_wc = None
                extracted_dur = None
                extracted_months = None
                extracted_weeks = None
                extracted_hours = None
                extracted_ext = None
                extracted_fte = None
                extracted_agency = None
                extracted_client = None
                req_skills = []
                pref_skills = []
                pain_points = ""
                is_remote = False
                t_warnings = []
                t_flags = []
                t_benefits = []

            # Apply manual overrides over extracted fields
            final_company = manual_company.strip() if manual_company.strip() else (extracted_company or "Target Company")
            final_title = manual_title.strip() if manual_title.strip() else (extracted_title or "Target Role")
            final_family = clean_family if manual_family != "Auto-Detect" else (extracted_family or "revenue_operations")
            final_min_pay = manual_min_pay if manual_min_pay > 0 else (extracted_min if extracted_min is not None and extracted_min > 0 else None)
            final_max_pay = manual_max_pay if manual_max_pay > 0 else (extracted_max if extracted_max is not None and extracted_max > 0 else None)
            final_url = manual_url.strip() if manual_url.strip() else (extracted_url or "")
            final_arr = clean_arrangement if manual_arrangement != "Auto-Detect" else (extracted_arr or "Employee")
            final_pb = clean_pay_basis if manual_pay_basis != "Auto-Detect" else (
                extracted_pb or ("Hourly" if (final_min_pay and final_min_pay < 500) else "Annual")
            )
            final_wc = clean_worker_class if manual_worker_class != "Auto-Detect" else (extracted_wc or "")
            final_dur = manual_duration.strip() if manual_duration.strip() else (extracted_dur or "")
            final_agency = manual_agency_client.strip() if manual_agency_client.strip() else (extracted_agency or "")
            final_client = extracted_client or ""

            # 2. Evaluate qualification and pay bounds
            t_qual_start = time.perf_counter()
            fit_eval = JobQualificationService.evaluate(
                company_name=final_company,
                job_title=final_title,
                raw_description=jd_text_input,
                required_skills=req_skills,
                preferred_skills=pref_skills,
                salary_min=final_min_pay,
                salary_max=final_max_pay,
                profile=st.session_state.get("profile"),
                existing_company_titles=all_opps,
                pay_basis=final_pb,
                expected_hours_per_week=extracted_hours,
                expected_hours_per_week_is_assumed=(extracted_hours is None),
                contract_length_months=extracted_months,
                contract_length_weeks=extracted_weeks,
                telemetry_warnings=t_warnings,
                telemetry_flags=t_flags,
                telemetry_benefits=t_benefits
            )
            t_qual_elapsed = time.perf_counter() - t_qual_start
            log_action(f"Step 2/5 [Qualification & Pay Bounds]: Completed in {t_qual_elapsed:.2f}s (Pay Range: {fit_eval.pay_bounds.display_range})")

            # 3. Best-fit resume selection
            selected_resume = resume_repo.select_best_fit_resume(final_title, final_family) if resume_repo else None
            resume_name = selected_resume.filename if selected_resume else "Default Resume"

            # 4. Drive workspace creation
            folder_link = None
            drive_jd_link = None
            drive_screening_doc_link = None
            if drive_adapter and getattr(drive_adapter, "is_connected", False):
                t_drv_start = time.perf_counter()
                try:
                    workspace = drive_adapter.create_application_workspace(final_company, final_title, opp_id)
                    folder_id = workspace.get("folder_id")
                    folder_link = workspace.get("folder_link")
                    if folder_id:
                        res_jd = drive_adapter.upload_raw_job_description(folder_id, jd_text_input, final_company, final_title)
                        drive_jd_link = res_jd.get("file_link") if isinstance(res_jd, dict) else None
                        if screening_inputs:
                            res_sq = drive_adapter.create_screening_questions_doc(folder_id, final_company, final_title, screening_inputs, opp_id)
                            drive_screening_doc_link = res_sq.get("file_link") if isinstance(res_sq, dict) else None
                        if selected_resume and getattr(selected_resume, "doc_id", None):
                            drive_adapter.export_resume_pdf(selected_resume.doc_id, folder_id, f"{resume_name}.pdf")
                        drive_adapter.mark_workspace_complete(folder_id)
                    t_drv_elapsed = time.perf_counter() - t_drv_start
                    log_action(f"Step 3/5 [Drive Workspace & Documents]: Completed in {t_drv_elapsed:.2f}s")
                except Exception as d_err:
                    log_warn(f"Step 3/5 [Drive Workspace & Documents]: Failed: {d_err}")
            else:
                log_action("Step 3/5 [Drive Workspace & Documents]: Skipped (drive disconnected or unconfigured)")

            # 5. Save local raw JD for deferred Role Intelligence
            try:
                raw_jd_dir = Path("output_reports") / uuid.uuid5(uuid.NAMESPACE_URL, opp_id).hex
                raw_jd_dir.mkdir(parents=True, exist_ok=True)
                (raw_jd_dir / "Raw_JD.txt").write_text(jd_text_input, encoding="utf-8")
            except Exception:
                pass

            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            final_status = "Processed" if fit_eval.is_qualified else fit_eval.status
            tokens_used = getattr(llm_adapter, "last_telemetry_tokens", 0)

            job_posting = JobPosting(
                opportunity_id=opp_id,
                company_name=final_company,
                job_title=final_title,
                title_family=final_family,
                raw_description=jd_text_input,
                source_url=final_url,
                opportunity_source="Outbound",
                category=manual_category,
                applied_via=clean_applied_via,
                priority=clean_priority,
                salary_expectation=manual_salary_expectation.strip(),
                notes=manual_notes.strip(),
                employment_arrangement=final_arr,
                worker_classification=final_wc,
                pay_basis=final_pb,
                contract_length_raw=final_dur,
                contract_length_months=extracted_months,
                contract_length_weeks=extracted_weeks,
                expected_hours_per_week=extracted_hours,
                expected_hours_per_week_is_assumed=(extracted_hours is None),
                extension_possible=extracted_ext,
                fte_conversion_possible=extracted_fte,
                staffing_agency=final_agency,
                client_company=final_client,
                required_skills=req_skills,
                preferred_skills=pref_skills,
                stage_history=[{"stage": final_status, "entered_at": now_iso}],
                selected_resume_name=resume_name,
                drive_folder_link=folder_link or "",
                drive_jd_link=drive_jd_link or "",
                drive_screening_doc_link=drive_screening_doc_link or "",
                screening_qa=screening_inputs,
                telemetry_warnings=t_warnings,
                telemetry_flags=t_flags,
                telemetry_benefits=t_benefits,
                tokens_used=tokens_used,
                role_intelligence_status="Not Generated"
            )

            t_store_start = time.perf_counter()
            saved = storage_adapter.save_opportunity(job_posting, fit_eval)
            t_store_elapsed = time.perf_counter() - t_store_start
            if saved:
                log_action(f"Step 4/5 [Storage Persistence]: Completed in {t_store_elapsed:.2f}s")
                log_action("Step 5/5 [Role Intelligence]: Deferred until interview stage or manual request")
                st.session_state.pop("crm_cached_opportunities", None)
                st.session_state[counter_key] = cur_idx + 1

                # If in Ingest & Apply, populate 1-tap application kit
                if view_context == "ingest":
                    st.session_state.latest_eval = {
                        "opp_id": opp_id,
                        "company": final_company,
                        "title": final_title,
                        "family": final_family,
                        "fit_eval": fit_eval,
                        "selected_resume": selected_resume,
                        "resume_name": resume_name,
                        "resume_link": getattr(selected_resume, "web_link", None) if selected_resume else None,
                        "folder_link": folder_link,
                        "drive_jd_link": drive_jd_link,
                        "drive_screening_doc_link": drive_screening_doc_link,
                        "screening_qa": screening_inputs,
                        "output_docx_path": None,
                        "docx_filename": "Role_Intelligence_Report.docx",
                        "role_intelligence_status": "Not Generated",
                        "req_skills": req_skills,
                        "pref_skills": pref_skills,
                        "pain_points": pain_points,
                        "is_remote": is_remote,
                        "telemetry_warnings": t_warnings,
                        "telemetry_flags": t_flags,
                        "telemetry_benefits": t_benefits,
                    }

                st.session_state["crm_flash_message"] = f"Job '{final_company} — {final_title}' saved to pipeline!"
                log_success(f"Job opportunity saved: {final_company} — {final_title}")
                st.rerun()
            else:
                log_warn(f"Step 4/5 [Storage Persistence]: Failed after {t_store_elapsed:.2f}s")
                st.error("Could not save opportunity to storage.")
