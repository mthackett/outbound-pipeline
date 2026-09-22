import os
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# Ensure project root is in sys.path for Streamlit
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

# Set page config as very first Streamlit command
st.set_page_config(
    page_title="Job Pipeline & Ingestion Cockpit",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

from job_pipeline.domain.models import (
    CandidateProfile, JobPosting, FitEvaluation, StakeholderContact, Touchpoint, ScreeningQA
)
from job_pipeline.domain.services import (
    JobQualificationService, ApplicationGuardrailService, ScreeningQAService
)
import importlib
import job_pipeline.adapters.secondary.google_sheets as gs_mod
importlib.reload(gs_mod)
from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter

import job_pipeline.adapters.secondary.google_drive as gd_mod
importlib.reload(gd_mod)
from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter
from job_pipeline.adapters.secondary.openai_adapter import OpenAIEngineAdapter
from job_pipeline.adapters.secondary.twilio_adapter import TwilioMessagingAdapter
from job_pipeline.adapters.secondary.gmail_adapter import GmailIngestionAdapter
from job_pipeline.adapters.secondary.mock_adapter import (
    MockJobStorageAdapter,
    MockDocumentStorageAdapter,
    MockResumeRepositoryAdapter,
    MockLLMStrategyAdapter
)

# Custom CSS styling for premium look & feel, responsive touch targets
st.markdown("""
<style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #F8FAFC;
        margin-bottom: 0.1rem;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #94A3B8;
        margin-bottom: 1.2rem;
    }
    .apply-kit-card {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.4rem;
        margin-bottom: 1.2rem;
    }
    .target-pay-box {
        background: linear-gradient(135deg, #1E1B4B 0%, #312E81 100%);
        border: 1.5px solid #6366F1;
        border-radius: 10px;
        padding: 1.2rem;
        color: #EEF2FF;
        margin-top: 0.8rem;
        margin-bottom: 1.2rem;
    }
    .recall-card {
        background-color: #0F172A;
        border-left: 5px solid #10B981;
        padding: 1.2rem;
        border-radius: 8px;
        margin-top: 0.8rem;
        margin-bottom: 1.2rem;
    }
    .quick-link-btn {
        display: inline-block;
        background-color: #2563EB;
        color: white !important;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        text-decoration: none;
        font-weight: 600;
        margin-right: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .quick-link-btn:hover {
        background-color: #1D4ED8;
    }
    .badge-pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        font-size: 0.85rem;
        border-radius: 9999px;
        background-color: #334155;
        color: #E2E8F0;
        margin-right: 0.4rem;
        margin-bottom: 0.4rem;
    }
</style>
""", unsafe_allow_html=True)


# Initialize Session State Objects
if "profile" not in st.session_state:
    st.session_state.profile = CandidateProfile()

if "latest_eval" not in st.session_state:
    st.session_state.latest_eval = None

if "pending_guardrail_check" not in st.session_state:
    st.session_state.pending_guardrail_check = None

if "num_screening_qa" not in st.session_state:
    st.session_state.num_screening_qa = 0


# Sidebar Configuration & Connections
st.sidebar.image("https://img.icons8.com/color/96/briefcase.png", width=56)
st.sidebar.title("Pipeline Controls")

demo_mode = st.sidebar.checkbox(
    "Zero-Cost Demo Mode",
    value=os.environ.get("DEMO_MODE", "false").lower() == "true",
    help="Uses mock fixtures and bypasses live API charges."
)

if demo_mode:
    storage_adapter = MockJobStorageAdapter()
    drive_adapter = MockDocumentStorageAdapter()
    resume_repo = MockResumeRepositoryAdapter()
    llm_adapter = MockLLMStrategyAdapter()
    twilio_adapter = TwilioMessagingAdapter()
else:
    storage_adapter = GoogleSheetsAdapter()
    drive_adapter = GoogleDriveAdapter()
    resume_repo = drive_adapter
    llm_adapter = OpenAIEngineAdapter()
    twilio_adapter = TwilioMessagingAdapter()

gmail_adapter = GmailIngestionAdapter()

# Guardrail Rules Configuration
with st.sidebar.expander("🛡️ Guardrail Rules & Limits", expanded=False):
    st.caption("Industry ATS guardrails to prevent auto-rejection.")
    s_max_apps = st.slider(
        "Max Concurrent Apps / Company",
        min_value=1, max_value=5,
        value=st.session_state.profile.max_company_applications_limit,
        help="Recruiter standard is max 2 active roles simultaneously."
    )
    s_window = st.slider(
        "Company Concurrency Window (Days)",
        min_value=15, max_value=180,
        value=st.session_state.profile.company_application_window_days,
        step=15,
        help="Rolling time window to count active applications at the same company."
    )
    s_repost = st.slider(
        "Repost Detection Window (Days)",
        min_value=30, max_value=180,
        value=st.session_state.profile.repost_detection_threshold_days,
        step=15,
        help="Applications older than this are treated as renewed reposts rather than duplicates."
    )
    st.session_state.profile.max_company_applications_limit = s_max_apps
    st.session_state.profile.company_application_window_days = s_window
    st.session_state.profile.repost_detection_threshold_days = s_repost

# Direct External Links
sheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
drive_root_id = os.environ.get("GOOGLE_APPLICATIONS_ROOT_FOLDER_ID", "")

st.sidebar.markdown("---")
st.sidebar.subheader("🔗 Quick Cloud Links")
if sheet_id:
    st.sidebar.markdown(f"[📊 Open Master Google Sheet](https://docs.google.com/spreadsheets/d/{sheet_id}/edit)")
if drive_root_id:
    st.sidebar.markdown(f"[📁 Open Drive Applications Root](https://drive.google.com/drive/folders/{drive_root_id})")

st.sidebar.markdown("---")
st.sidebar.subheader("🔌 Connection Status")
st.sidebar.write(f"**Sheets API**: {'🟢 Connected' if storage_adapter.is_connected else '🔴 Offline/Demo'}")
st.sidebar.write(f"**Drive API**:  {'🟢 Connected' if drive_adapter.is_connected else '🔴 Offline/Demo'}")
st.sidebar.write(f"**OpenAI API**: {'🟢 Ready' if getattr(llm_adapter, 'api_key', None) else '🔴 No API Key'}")
st.sidebar.write(f"**Twilio**: {'🟡 Simulation (Staged)' if not twilio_adapter.is_connected else '🟢 Live'}")

st.sidebar.markdown("---")
st.sidebar.caption("Job Application Pipeline CRM v1.3")


# Main Dashboard Header
st.markdown('<div class="main-title">🚀 Job Application Pipeline & Apply Cockpit</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Automated JD Ingestion · 60%–80% Target Pay · Google Drive Workspace · Best Resume Match · Google Sheets CRM</div>', unsafe_allow_html=True)


# Main Tabs: Focused on Ingestion, Live Pipeline CRM, and Future Expansion
tab1, tab2, tab3 = st.tabs([
    "⚡ Fast Ingestion & Apply Kit",
    "📊 Pipeline Tracker & CRM",
    "🔮 Integrations & Future Modules"
])


# =====================================================================
# TAB 1: FAST INGESTION & APPLY KIT (ZERO FRICTION)
# =====================================================================
with tab1:
    st.markdown("### 1. Paste Job Posting Text")
    st.caption("Paste the full job description from LinkedIn, Indeed, or company careers page. The AI automatically extracts the company, title, salary, skills, and matches your best resume.")

    jd_text_input = st.text_area(
        "Job Description Text",
        height=240,
        placeholder="Paste full job description text here...",
        label_visibility="collapsed"
    )

    with st.expander("⚙️ Advanced / Manual Overrides (Optional)", expanded=False):
        st.caption("Leave blank to let AI auto-extract automatically.")
        col_ov1, col_ov2, col_ov3 = st.columns(3)
        with col_ov1:
            manual_company = st.text_input("Override Company Name", placeholder="Auto-detect from text")
            manual_title = st.text_input("Override Job Title", placeholder="Auto-detect from text")
        with col_ov2:
            manual_family = st.selectbox(
                "Role Family",
                ["Auto-Detect", "revenue_operations", "revenue_systems", "business_analytics", "gtm_engineering", "solutions_implementation"]
            )
            manual_url = st.text_input("Job Source URL", placeholder="https://linkedin.com/jobs/...")
        with col_ov3:
            manual_min_pay = st.number_input("Override Min Salary ($)", value=0, step=5000)
            manual_max_pay = st.number_input("Override Max Salary ($)", value=0, step=5000)

    # 2. Optional Application Screening Questions & Answers
    with st.expander("📝 Application Screening Questions & Custom Answers (Optional)", expanded=False):
        st.caption("Optionally record questions and answers requested on this application. When provided, they are saved into a dedicated 'Screening Questions' Google Doc in your Drive folder and logged into your reusable master Q&A library.")

        col_q_actions = st.columns([1, 1, 3])
        with col_q_actions[0]:
            if st.button("➕ Add Question"):
                st.session_state.num_screening_qa += 1
                st.rerun()
        with col_q_actions[1]:
            if st.session_state.num_screening_qa > 0:
                if st.button("➖ Remove Last"):
                    st.session_state.num_screening_qa -= 1
                    st.rerun()

        screening_inputs = []
        for i in range(st.session_state.num_screening_qa):
            st.markdown(f"---")
            st.markdown(f"**Screening Question {i + 1}**")
            cq1, cq2 = st.columns([3, 1])
            with cq1:
                q_text = st.text_input(f"Question Prompt", key=f"sq_q_{i}", placeholder="e.g. Describe your experience with Salesforce & dbt.")
            with cq2:
                q_cat = st.selectbox(f"Category", ["General", "Technical", "Salary", "Experience", "Culture"], key=f"sq_cat_{i}")

            ca1, ca2 = st.columns([4, 1])
            with ca1:
                ans_text = st.text_area(f"Your Answer", key=f"sq_a_{i}", height=85, placeholder="Enter your response for this application...")
            with ca2:
                ai_draft_btn = st.button(f"✨ Draft with AI", key=f"sq_ai_{i}", help="Draft a tailored answer using your profile & the JD")
                if ai_draft_btn:
                    if not q_text:
                        st.warning("Please enter a question prompt first.")
                    else:
                        with st.spinner("Drafting answer with AI..."):
                            if not demo_mode and isinstance(llm_adapter, OpenAIEngineAdapter) and getattr(llm_adapter, "client", None):
                                try:
                                    draft_prompt = (
                                        f"You are helping candidate {st.session_state.profile.candidate_name} answer a screening question.\n"
                                        f"Core strengths: {', '.join(st.session_state.profile.core_strengths)}.\n"
                                        f"Target role: {manual_title or 'RevOps / Analytics professional'}.\n"
                                        f"Target company: {manual_company or 'Tech Company'}.\n"
                                        f"Job Description excerpt: {jd_text_input[:800] if jd_text_input else 'N/A'}\n"
                                        f"Screening Question: {q_text}\n\n"
                                        f"Write a concise, high-impact, professional application answer (2-4 sentences or tight bullet points). Make it ATS-friendly and confident."
                                    )
                                    resp = llm_adapter.client.chat.completions.create(
                                        model="gpt-4o-mini",
                                        messages=[{"role": "user", "content": draft_prompt}],
                                        temperature=0.4,
                                        max_tokens=250
                                    )
                                    drafted = resp.choices[0].message.content.strip()
                                    st.session_state[f"sq_a_{i}"] = drafted
                                    st.rerun()
                                except Exception as d_err:
                                    st.error(f"AI draft notice: {d_err}")
                            else:
                                st.session_state[f"sq_a_{i}"] = (
                                    f"I bring deep expertise across {st.session_state.profile.core_strengths[0]} and {st.session_state.profile.core_strengths[1]}, "
                                    f"having scaled reporting models, automated data funnels, and partnered cross-functionally to accelerate revenue pipeline."
                                )
                                st.rerun()

            if q_text and ans_text:
                screening_inputs.append(ScreeningQA(question=q_text, answer=ans_text, category=q_cat))

    def execute_application_workflow(job_payload: dict):
        with st.spinner("Processing job, generating Google Drive workspace, documents, and logging to Sheets..."):
            final_company = job_payload["company"]
            final_title = job_payload["title"]
            final_family = job_payload["family"]
            final_min_pay = job_payload["min_pay"]
            final_max_pay = job_payload["max_pay"]
            final_url = job_payload["url"]
            req_skills = job_payload["req_skills"]
            pref_skills = job_payload["pref_skills"]
            pain_points = job_payload["pain_points"]
            is_remote = job_payload["is_remote"]
            screening_qa_list = job_payload["screening_qa"]
            jd_text = job_payload["jd_text"]
            all_opps = job_payload["all_opps"]

            # 1. Fit Qualification & Target Pay Calculator (60%-80%)
            fit_eval = JobQualificationService.evaluate(
                company_name=final_company,
                job_title=final_title,
                raw_description=jd_text,
                required_skills=req_skills,
                preferred_skills=pref_skills,
                salary_min=final_min_pay,
                salary_max=final_max_pay,
                profile=st.session_state.profile,
                existing_company_titles=all_opps
            )

            # 2. Select Best Fit Resume
            selected_resume = resume_repo.select_best_fit_resume(final_title, final_family)
            resume_name = selected_resume.filename if selected_resume else "Default Resume"
            resume_link = getattr(selected_resume, "web_link", None) if selected_resume else None
            if not resume_link and selected_resume and selected_resume.doc_id and not selected_resume.doc_id.startswith("doc_"):
                resume_link = f"https://docs.google.com/document/d/{selected_resume.doc_id}/edit"

            # 3. Create Google Drive Application Workspace Folder
            workspace = drive_adapter.create_application_workspace(final_company, final_title)
            folder_id = workspace.get("folder_id")
            folder_link = workspace.get("folder_link")

            # 4. Save Raw Job Description Document into Drive Folder (Reliable Upload)
            drive_jd_link = None
            if folder_id:
                res_jd = drive_adapter.upload_raw_job_description(
                    folder_id,
                    jd_text,
                    company_name=final_company,
                    job_title=final_title
                )
                if isinstance(res_jd, dict):
                    drive_jd_link = res_jd.get("file_link")

            # 5. Create 'Screening Questions' Google Doc if questions were provided
            drive_screening_doc_link = None
            opp_id = str(uuid.uuid4())
            if folder_id and screening_qa_list:
                res_sq = drive_adapter.create_screening_questions_doc(
                    folder_id=folder_id,
                    company_name=final_company,
                    job_title=final_title,
                    qa_items=screening_qa_list,
                    opportunity_id=opp_id
                )
                if isinstance(res_sq, dict):
                    drive_screening_doc_link = res_sq.get("file_link")

            # 6. Generate Role Intelligence Report (.docx)
            docx_filename = f"{final_company.replace(' ', '_')}_Role_Intelligence_Report.docx"
            output_docx_path = f"output_reports/{docx_filename}"
            os.makedirs("output_reports", exist_ok=True)

            resume_text = resume_repo.fetch_resume_text(selected_resume.doc_id) if selected_resume else ""
            report = llm_adapter.generate_role_intelligence_report(
                job_data={"company": final_company, "title": final_title, "description": jd_text},
                resume_data={"resume_id": selected_resume.doc_id if selected_resume else "res1", "text": resume_text},
                output_docx_path=output_docx_path,
                target_pay_bounds=fit_eval.pay_bounds.model_dump(),
                demo_mode=demo_mode
            )

            # Upload Resume PDF and DOCX Report to Folder
            if folder_id:
                if selected_resume and selected_resume.doc_id:
                    drive_adapter.export_resume_pdf(selected_resume.doc_id, folder_id, f"{resume_name}.pdf")
                if os.path.exists(output_docx_path):
                    drive_adapter.upload_role_intelligence_report(folder_id, output_docx_path)

            # 7. Save Opportunity to Google Sheets (Raw Ingestion & Screening QA)
            tot_tokens = getattr(llm_adapter, "last_telemetry_tokens", 0) + getattr(llm_adapter, "last_report_tokens", 0)
            job_posting = JobPosting(
                opportunity_id=opp_id,
                company_name=final_company,
                job_title=final_title,
                title_family=final_family,
                raw_description=jd_text,
                source_url=final_url,
                required_skills=req_skills,
                preferred_skills=pref_skills,
                selected_resume_name=resume_name,
                drive_folder_link=folder_link,
                drive_jd_link=drive_jd_link,
                drive_screening_doc_link=drive_screening_doc_link,
                screening_qa=screening_qa_list,
                tokens_used=tot_tokens
            )
            storage_adapter.save_opportunity(job_posting, fit_eval)

            # Clear pending guardrail check
            st.session_state.pending_guardrail_check = None

            # Store in session state for rendering Apply Kit
            st.session_state.latest_eval = {
                "company": final_company,
                "title": final_title,
                "family": final_family,
                "fit_eval": fit_eval,
                "selected_resume": selected_resume,
                "resume_name": resume_name,
                "resume_link": resume_link,
                "folder_link": folder_link,
                "drive_jd_link": drive_jd_link,
                "drive_screening_doc_link": drive_screening_doc_link,
                "screening_qa": screening_qa_list,
                "output_docx_path": output_docx_path,
                "docx_filename": docx_filename,
                "req_skills": req_skills,
                "pref_skills": pref_skills,
                "pain_points": pain_points,
                "is_remote": is_remote,
                "opp_id": opp_id
            }

    # Display Pending Guardrail Warning if tripped
    if st.session_state.pending_guardrail_check:
        chk = st.session_state.pending_guardrail_check
        dup = chk["dup"]
        vel = chk["vel"]

        st.warning("⚠️ **Application Guardrail Warning** — Review Before Submitting")
        if dup["is_duplicate"] and not dup["is_repost"]:
            matched_title = dup["matched_record"].get("Job Title") if dup["matched_record"] else chk["title"]
            st.error(
                f"🚨 **Duplicate Application Detected**: You already applied to **{matched_title}** at **{chk['company']}** "
                f"{dup['days_elapsed']} days ago ({dup['prior_date']}). Current Status: `{dup['prior_status']}`.\n\n"
                f"*Note: Many ATS platforms (Greenhouse, Lever, Workday) automatically archive or reject duplicate applications submitted within 60 days.*"
            )

        if dup["is_repost"]:
            st.info(
                f"ℹ️ **Potential Repost / Renewed Requisition**: You previously applied to this role at {chk['company']} "
                f"{dup['days_elapsed']} days ago ({dup['prior_date']}). Re-applying may be viable if the hiring requisition has been refreshed."
            )

        if vel["velocity_exceeded"]:
            st.error(
                f"🏢 **Company Application Velocity Cap Reached**: You already have **{vel['active_count']} application(s)** "
                f"with **{chk['company']}** within the past {vel['window_days']} days (Guardrail Cap: {vel['max_limit']}).\n\n"
                f"*Note: Internal talent acquisition teams often flag candidates with multiple concurrent applications as lack of focus.*"
            )
            st.markdown("**Recent Applications at this Company:**")
            st.dataframe(vel["active_applications"], use_container_width=True)

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if st.button("👉 Proceed & Apply Anyway (Override)", type="primary", use_container_width=True):
                execute_application_workflow(chk)
                st.rerun()
        with col_g2:
            if st.button("❌ Cancel / Hold Application", use_container_width=True):
                st.session_state.pending_guardrail_check = None
                st.info("Ingestion cancelled. You can edit your inputs or select another job.")
                st.rerun()

    # Primary Action Button
    if st.button("⚡ Process Job & Generate Apply Kit", type="primary", use_container_width=True):
        if not jd_text_input or len(jd_text_input.strip()) < 20:
            st.error("Please paste a valid job description (at least 20 characters).")
        else:
            with st.spinner("Analyzing job description and checking guardrails..."):
                # 0. Telemetry Extraction via OpenAI gpt-4o-mini
                telemetry = None
                extracted_company = ""
                extracted_title = ""
                extracted_family = "revenue_operations"
                extracted_min = None
                extracted_max = None
                req_skills = []
                pref_skills = []
                pain_points = ""
                is_remote = False

                if not demo_mode and isinstance(llm_adapter, OpenAIEngineAdapter):
                    try:
                        telemetry = llm_adapter.extract_job_telemetry(jd_text_input)
                        extracted_company = telemetry.company_name
                        extracted_title = telemetry.job_title
                        extracted_family = telemetry.title_family
                        extracted_min = telemetry.requirements.salary_min
                        extracted_max = telemetry.requirements.salary_max
                        req_skills = telemetry.requirements.required_tech_stack
                        pref_skills = telemetry.requirements.preferred_tech_stack
                        pain_points = telemetry.requirements.core_pain_points or ""
                        is_remote = telemetry.requirements.is_remote
                    except Exception as e:
                        st.warning(f"Telemetry auto-extraction notice: {e}")
                        req_skills, pref_skills = ["Salesforce", "SQL", "Tableau", "Clari"], ["dbt"]
                else:
                    extracted_company = "Planful"
                    extracted_title = "Sales Operations Analyst"
                    extracted_family = "revenue_operations"
                    extracted_min = 110000
                    extracted_max = 135000
                    req_skills = ["Salesforce", "SQL", "Tableau", "Clari"]
                    pref_skills = ["Territory Planning"]
                    pain_points = "Translating messy operational data into clean executive forecasts."

                # Apply Overrides if specified
                final_company = manual_company.strip() if manual_company and manual_company.strip() else (extracted_company or "Target Company")
                final_title = manual_title.strip() if manual_title and manual_title.strip() else (extracted_title or "Target Role")
                final_family = manual_family if manual_family != "Auto-Detect" else (extracted_family or "revenue_operations")
                final_min_pay = manual_min_pay if manual_min_pay > 0 else extracted_min
                final_max_pay = manual_max_pay if manual_max_pay > 0 else extracted_max
                final_url = manual_url.strip() if manual_url and manual_url.strip() else (telemetry.source_url if telemetry else None)

                # Fetch all existing opportunities for guardrail checking
                all_opps = storage_adapter.fetch_all_opportunities()

                # Guardrail Evaluation: Duplicate & Velocity Checks
                dup_res = ApplicationGuardrailService.check_duplicate(
                    company_name=final_company,
                    job_title=final_title,
                    existing_records=all_opps,
                    repost_threshold_days=st.session_state.profile.repost_detection_threshold_days
                )
                vel_res = ApplicationGuardrailService.check_company_velocity(
                    company_name=final_company,
                    existing_records=all_opps,
                    max_limit=st.session_state.profile.max_company_applications_limit,
                    window_days=st.session_state.profile.company_application_window_days
                )

                job_payload = {
                    "company": final_company,
                    "title": final_title,
                    "family": final_family,
                    "min_pay": final_min_pay,
                    "max_pay": final_max_pay,
                    "url": final_url,
                    "req_skills": req_skills,
                    "pref_skills": pref_skills,
                    "pain_points": pain_points,
                    "is_remote": is_remote,
                    "screening_qa": screening_inputs,
                    "jd_text": jd_text_input,
                    "all_opps": all_opps,
                    "dup": dup_res,
                    "vel": vel_res
                }

                # Check if Guardrails are tripped
                if (dup_res["is_duplicate"] and not dup_res["is_repost"]) or vel_res["velocity_exceeded"]:
                    st.session_state.pending_guardrail_check = job_payload
                    st.session_state.latest_eval = None
                    st.rerun()
                else:
                    # Clean check -> proceed directly
                    execute_application_workflow(job_payload)
                    st.rerun()

    # Render Apply Kit if evaluation exists
    if st.session_state.latest_eval:
        ev = st.session_state.latest_eval
        st.markdown("---")
        st.subheader("🎯 1-Tap Application Kit")

        # Top Summary Metrics
        m1, m2, m3 = st.columns(3)
        with m1:
            status_symbol = "🟢" if ev["fit_eval"].status == "PASS" else "🔴"
            st.metric("Fit Status", f"{status_symbol} {ev['fit_eval'].status}")
        with m2:
            st.metric("Skill Match Score", f"{int(ev['fit_eval'].fit_score * 100)}%")
        with m3:
            st.metric("Company & Role", f"{ev['company']} — {ev['title']}")

        # Primary Action Bar (Buttons to open Resume, Drive Folder, Docs, Sheet)
        st.markdown("#### ⚡ Immediate Application Actions:")
        action_col1, action_col2, action_col3, action_col4 = st.columns(4)

        with action_col1:
            if ev.get("resume_link"):
                st.link_button(
                    "📄 Open Matched Resume",
                    ev["resume_link"],
                    type="primary",
                    use_container_width=True,
                    help="Opens your selected Google Doc resume in Google Drive"
                )
            else:
                st.button("📄 Selected: " + ev["resume_name"][:20], disabled=True, use_container_width=True)

        with action_col2:
            if ev.get("folder_link"):
                st.link_button(
                    "📁 Drive Workspace Folder",
                    ev["folder_link"],
                    use_container_width=True,
                    help="Opens the dedicated application workspace folder in Google Drive"
                )
            else:
                st.button("📁 Drive Folder (Mock)", disabled=True, use_container_width=True)

        with action_col3:
            if ev.get("drive_jd_link"):
                st.link_button(
                    "📄 Raw JD Doc (Drive)",
                    ev["drive_jd_link"],
                    use_container_width=True,
                    help="Opens the saved Job Description Google Doc in Drive"
                )
            else:
                st.link_button(
                    "📊 Open Google Sheet",
                    f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
                    use_container_width=True,
                    help="Opens the master Google Sheets pipeline tracker"
                )

        with action_col4:
            if ev.get("drive_screening_doc_link"):
                st.link_button(
                    "📝 Screening Questions Doc",
                    ev["drive_screening_doc_link"],
                    use_container_width=True,
                    help="Opens the Screening Questions Google Doc in Drive"
                )
            elif os.path.exists(ev["output_docx_path"]):
                with open(ev["output_docx_path"], "rb") as df:
                    st.download_button(
                        label="📥 Download .docx Brief",
                        data=df,
                        file_name=ev["docx_filename"],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )

        # Target Salary Negotiation Box
        pb = ev["fit_eval"].pay_bounds
        st.markdown(f"""
        <div class="target-pay-box">
            <h4 style="margin:0; color:#C7D2FE;">💰 Desired Salary Answer (60% – 80% Target Anchor)</h4>
            <h2 style="margin:6px 0; color:#FFFFFF; font-weight:800;">{pb.display_range}</h2>
            <p style="margin:0; font-size:0.92rem; color:#A5B4FC;">
                <b>For application form:</b> Anchor at <b>${pb.target_min:,.0f}</b> or enter range <b>${pb.target_min:,.0f} – ${pb.target_max:,.0f}</b>.
                (Calculated from posted base spread: ${pb.posted_min:,.0f} – ${pb.posted_max:,.0f})
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Screening Q&A Display Box if submitted
        if ev.get("screening_qa"):
            with st.expander(f"📝 Submitted Screening Questions & Answers ({len(ev['screening_qa'])})", expanded=True):
                st.caption("Copy answers directly into the ATS application form or review during phone screens.")
                clipboard_text = ScreeningQAService.format_qa_clipboard_summary(ev["screening_qa"])
                st.code(clipboard_text, language="text")
                if ev.get("drive_screening_doc_link"):
                    st.markdown(f"[↗ Open 'Screening Questions' Google Doc in Drive]({ev['drive_screening_doc_link']})")

        # 10-Second Phone Screen Recall Card
        st.markdown(f"""
        <div class="recall-card">
            <h3 style="margin:0 0 8px 0; color:#10B981;">📞 10-Second Phone Screen Recall Card</h3>
            <p style="margin:4px 0;"><b>Target Role:</b> {ev['title']} at {ev['company']} {'(Remote)' if ev.get('is_remote') else ''}</p>
            <p style="margin:4px 0;"><b>Matched Resume:</b> {ev['resume_name']}</p>
            <p style="margin:4px 0;"><b>Compensation Strategy:</b> Anchor base at <b>${pb.target_min:,.0f} - ${pb.target_max:,.0f}</b>.</p>
            <p style="margin:4px 0;"><b>Core Pain Points:</b> {ev.get('pain_points') or 'Scaling revenue reporting, pipeline velocity, and cross-functional visibility.'}</p>
            <p style="margin:4px 0;"><b>Required Skills Highlight:</b> {', '.join(ev.get('req_skills', [])[:5]) or 'Salesforce, SQL, RevOps, dbt'}</p>
        </div>
        """, unsafe_allow_html=True)

        # Extracted Tech Stack Badges
        if ev.get("req_skills") or ev.get("pref_skills"):
            st.markdown("<b>Tech Stack Extracted:</b>", unsafe_allow_html=True)
            pills_html = ""
            for s in ev.get("req_skills", []):
                pills_html += f'<span class="badge-pill" style="background-color:#1E3A8A; color:#BFDBFE;">✓ {s}</span>'
            for s in ev.get("pref_skills", []):
                pills_html += f'<span class="badge-pill" style="background-color:#334155; color:#CBD5E1;">+ {s}</span>'
            st.markdown(pills_html, unsafe_allow_html=True)


# =====================================================================
# TAB 2: PIPELINE TRACKER & LIGHTWEIGHT CRM
# =====================================================================
with tab2:
    st.subheader("📊 Live Application Pipeline & CRM")
    st.caption("Active applications synced in real-time from your Google Sheet (`Raw Ingestion`). Update stages, add recruiter contact info, and track interview progress.")

    col_btn_refresh, col_sheet_link = st.columns([1, 2])
    with col_btn_refresh:
        refresh_clicked = st.button("🔄 Refresh Pipeline from Google Sheets")
    with col_sheet_link:
        st.markdown(f"[↗ View Full Spreadsheet in Google Sheets](https://docs.google.com/spreadsheets/d/{sheet_id}/edit)")

    opportunities = []
    all_screening_qa = []
    if storage_adapter.is_connected:
        try:
            opportunities = storage_adapter.fetch_all_opportunities(force_refresh=refresh_clicked)
            all_screening_qa = storage_adapter.fetch_screening_qa(force_refresh=refresh_clicked)
        except Exception as e:
            st.warning(f"Could not load rows from Google Sheets: {e}")
    else:
        opportunities = [
            {
                "Opportunity ID": "demo-1",
                "Company Name": "Planful",
                "Job Title": "Sales Operations Analyst",
                "Status": "Processed",
                "Target Pay Range": "$125,000 - $130,000",
                "Date Created": "2026-09-19",
                "Selected Resume": "Matthew Hackett Revenue Operations Analyst Resume",
                "Drive Folder Link": "https://drive.google.com",
                "Notes": "Sarah Jenkins (Recruiter) - Initial phone screen scheduled for Tuesday."
            }
        ]
        all_screening_qa = []

    # Map screening QA by opportunity_id in-memory (0 extra Sheets API calls)
    opp_qa_map = {}
    for item in all_screening_qa:
        oid = str(item.get("opportunity_id", "")).strip()
        if oid:
            opp_qa_map.setdefault(oid, []).append(item)

    if opportunities:
        # High Level Pipeline Metrics
        total_apps = len(opportunities)
        processed_count = sum(1 for o in opportunities if str(o.get("Status")).strip() in ["Processed", "Applied"])
        interviewing_count = sum(1 for o in opportunities if "Screen" in str(o.get("Status")) or "Interview" in str(o.get("Status")) or "Manager" in str(o.get("Status")))
        flagged_count = sum(1 for o in opportunities if "Flagged" in str(o.get("Status")))

        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
        stat_col1.metric("Total Tracked", total_apps)
        stat_col2.metric("Applied / Processed", processed_count)
        stat_col3.metric("Active Interviewing", interviewing_count)
        stat_col4.metric("Flagged / Disqualified", flagged_count)

        # Search / Filter Bar
        search_query = st.text_input("🔍 Search Applications by Company, Role, or Status", placeholder="e.g. Planful, Analyst, Recruiter Screen...")

        filtered_opps = opportunities
        if search_query:
            sq = search_query.lower()
            filtered_opps = [
                o for o in opportunities
                if sq in str(o.get("Company Name", "")).lower()
                or sq in str(o.get("Job Title", "")).lower()
                or sq in str(o.get("Status", "")).lower()
                or sq in str(o.get("Notes", "")).lower()
            ]

        st.markdown(f"Showing **{len(filtered_opps)}** opportunities (newest first):")

        # Render each application card
        for idx, opp in enumerate(reversed(filtered_opps)):
            comp = opp.get("Company Name", "Unknown Company")
            title = opp.get("Job Title", "Unknown Role")
            curr_status = opp.get("Status", "Pending")
            target_pay = opp.get("Target Pay Range", "N/A")
            opp_id = opp.get("Opportunity ID", f"row-{idx}")
            drive_link = opp.get("Drive Folder Link", "")
            notes = opp.get("Notes", "")
            date_added = opp.get("Date Created", "")

            # Status Icon
            if "Offer" in curr_status:
                s_icon = "🎉"
            elif "Interview" in curr_status or "Screen" in curr_status or "Manager" in curr_status:
                s_icon = "📞"
            elif curr_status == "Applied":
                s_icon = "📤"
            elif "Flagged" in curr_status:
                s_icon = "⚠️"
            else:
                s_icon = "📋"

            with st.expander(f"{s_icon} **{comp}** — {title}  |  *Status:* `{curr_status}`  |  *Pay:* `{target_pay}`"):
                c_card1, c_card2 = st.columns([1, 1])

                with c_card1:
                    st.write(f"**Date Created**: {date_added or 'Recent'}")
                    st.write(f"**Target Pay**: {target_pay or 'Not calculated'}")
                    st.write(f"**Selected Resume**: {opp.get('Selected Resume') or 'None'}")
                    if drive_link:
                        st.markdown(f"[📁 Open Application Drive Folder]({drive_link})")
                    screening_doc = opp.get("Screening Doc Link")
                    if screening_doc:
                        st.markdown(f"[📝 Open Screening Questions Doc]({screening_doc})")
                    if opp.get("Fit Warning"):
                        st.caption(f"🛡️ Guardrail Note: {opp.get('Fit Warning')}")

                with c_card2:
                    st.markdown("##### Update Stage & Recruiter Contact:")
                    stage_options = [
                        "Pending", "Processed", "Applied",
                        "Recruiter Screen", "Hiring Manager",
                        "Technical Screen", "Final Round", "Offer",
                        "Archived / Rejected"
                    ]
                    current_idx = stage_options.index(curr_status) if curr_status in stage_options else 1

                    new_stage = st.selectbox(
                        "Interview Stage",
                        stage_options,
                        index=current_idx,
                        key=f"stage_sel_{opp_id}_{idx}"
                    )
                    new_notes = st.text_area(
                        "Recruiter Contacts & Interview Notes",
                        value=notes,
                        height=70,
                        placeholder="e.g. Recruiter Sarah (sjenkins@planful.com). Focus on ARR metrics.",
                        key=f"notes_ta_{opp_id}_{idx}"
                    )

                    if st.button("💾 Save Status & Notes", key=f"save_btn_{opp_id}_{idx}"):
                        if storage_adapter.is_connected:
                            success = storage_adapter.update_opportunity_status(opp_id, new_stage, new_notes)
                            if success:
                                st.success(f"Updated {comp} to '{new_stage}' in Google Sheets!")
                            else:
                                st.error("Failed to update status in Google Sheets.")
                        else:
                            st.info(f"Simulated update: {comp} set to '{new_stage}' (Demo Mode).")

                # Section A: Structured Call & Interview Logger
                with st.expander("📞 Log Call / Interview Notes", expanded=False):
                    st.caption("Record phone screen or interview discussion points. Submits on button click or Enter.")
                    with st.form(key=f"call_form_{opp_id}_{idx}", clear_on_submit=True):
                        c_call1, c_call2 = st.columns([1, 1])
                        with c_call1:
                            call_type = st.selectbox(
                                "Call / Interview Stage",
                                ["Recruiter Screen", "Hiring Manager", "Technical Interview", "Final Round", "Offer Negotiation", "Ad-hoc Catchup"],
                                key=f"call_type_{opp_id}_{idx}"
                            )
                        with c_call2:
                            interviewer = st.text_input(
                                "Interviewer Name & Role",
                                placeholder="e.g. Sarah Jenkins (VP of RevOps)",
                                key=f"interviewer_{opp_id}_{idx}"
                            )
                        call_takeaway = st.text_area(
                            "Key Discussion Notes & Next Steps",
                            placeholder="e.g. Discussed data stack (dbt + Snowflake). Excited about automated pipeline project. Follow up by Friday with case study.",
                            height=75,
                            key=f"call_notes_{opp_id}_{idx}"
                        )
                        btn_call_submitted = st.form_submit_button("➕ Append Call Note to Tracker")
                        if btn_call_submitted:
                            if call_takeaway.strip():
                                if storage_adapter.is_connected and hasattr(storage_adapter, "append_call_note"):
                                    success = storage_adapter.append_call_note(
                                        opportunity_id=opp_id,
                                        note_text=call_takeaway,
                                        call_type=call_type,
                                        interviewer=interviewer
                                    )
                                    if success:
                                        st.success("Call note appended to Google Sheets tracker!")
                                        st.rerun()
                                    else:
                                        st.error("Failed to append call note.")
                                else:
                                    st.info("Simulated: Call note appended (Demo Mode).")
                            else:
                                st.warning("Please enter note text before appending.")

                # Section B: Application Screening Questions Manager
                with st.expander("📝 Screening Questions & Answers for this Role", expanded=False):
                    st.caption("Manage custom Q&As for this application. Updates Google Sheets and syncs with the Google Doc in your Drive folder.")

                    # Look up existing Q&A from in-memory map (0 API calls)
                    opp_qa_list = opp_qa_map.get(opp_id, [])

                    if opp_qa_list:
                        st.markdown(f"**Recorded Questions ({len(opp_qa_list)}):**")
                        for q_i, q_item in enumerate(opp_qa_list):
                            cat_tag = f"[{q_item.get('category', 'General')}] " if q_item.get('category') else ""
                            st.markdown(f"**{q_i + 1}. {cat_tag}{q_item.get('question', '')}**")
                            st.info(q_item.get('answer', ''))
                    else:
                        st.caption("No screening questions recorded yet for this application.")

                    st.markdown("---")
                    st.markdown("##### ➕ Add / Append Screening Question:")

                    # AI Draft Assistant outside form to enable interactive pre-population
                    col_ai_prompt, col_ai_btn = st.columns([3, 1])
                    with col_ai_prompt:
                        ai_prompt_hint = st.text_input(
                            "Topic or Question to Draft with AI (Optional)",
                            placeholder="e.g. Experience with HubSpot or salary expectations",
                            key=f"ai_hint_{opp_id}_{idx}"
                        )
                    with col_ai_btn:
                        st.write("")
                        btn_draft_ai = st.button("✨ Draft with AI", key=f"btn_ai_draft_{opp_id}_{idx}")

                    draft_ans_key = f"draft_ans_val_{opp_id}_{idx}"
                    if btn_draft_ai:
                        if not ai_prompt_hint.strip():
                            st.warning("Please enter a topic or question to draft.")
                        elif hasattr(llm_adapter, "client") and getattr(llm_adapter, "api_key", None):
                            try:
                                draft_prompt = (
                                    f"You are helping candidate {st.session_state.profile.candidate_name} answer an application screening question.\n"
                                    f"Core strengths: {', '.join(st.session_state.profile.core_strengths)}.\n"
                                    f"Target role: {title}.\n"
                                    f"Target company: {comp}.\n"
                                    f"Screening Question: {ai_prompt_hint}\n\n"
                                    f"Write a concise, high-impact, professional application answer (2-4 sentences or tight bullet points). Make it ATS-friendly and confident."
                                )
                                resp = llm_adapter.client.chat.completions.create(
                                    model="gpt-4o-mini",
                                    messages=[{"role": "user", "content": draft_prompt}],
                                    temperature=0.4,
                                    max_tokens=250
                                )
                                st.session_state[draft_ans_key] = resp.choices[0].message.content.strip()
                                st.rerun()
                            except Exception as d_err:
                                st.error(f"AI draft notice: {d_err}")

                    # Form encapsulates typing to completely eliminate typing-time API calls
                    with st.form(key=f"qa_form_{opp_id}_{idx}", clear_on_submit=False):
                        q_new_prompt = st.text_input(
                            "Screening Question Prompt",
                            value=ai_prompt_hint if ai_prompt_hint else "",
                            placeholder="e.g. Describe your experience scaling HubSpot to Salesforce syncs.",
                            key=f"new_q_prompt_{opp_id}_{idx}"
                        )
                        q_new_cat = st.selectbox(
                            "Category",
                            ["General", "Technical", "Salary", "Experience", "Culture"],
                            key=f"new_q_cat_{opp_id}_{idx}"
                        )
                        initial_ans = st.session_state.get(draft_ans_key, "")
                        q_new_ans = st.text_area(
                            "Your Answer",
                            value=initial_ans,
                            height=90,
                            placeholder="Enter or refine your answer here...",
                            key=f"new_q_ans_{opp_id}_{idx}"
                        )

                        btn_save_qa = st.form_submit_button("💾 Save Question & Sync to Drive")
                        if btn_save_qa:
                            if not q_new_prompt.strip() or not q_new_ans.strip():
                                st.warning("Please enter both the question and answer.")
                            else:
                                new_qa_obj = ScreeningQA(
                                    question=q_new_prompt.strip(),
                                    answer=q_new_ans.strip(),
                                    category=q_new_cat
                                )

                                # 1. Save to Google Sheets
                                if storage_adapter.is_connected:
                                    storage_adapter.save_screening_qa(
                                        opportunity_id=opp_id,
                                        company_name=comp,
                                        job_title=title,
                                        qa_items=[new_qa_obj]
                                    )

                                # 2. Extract folder_id from drive_link if available and sync Google Doc
                                gdoc_url = None
                                folder_id_match = re.search(r'folders/([a-zA-Z0-9_-]+)', drive_link) if drive_link else None
                                folder_target_id = folder_id_match.group(1) if folder_id_match else None

                                if drive_adapter.is_connected and folder_target_id:
                                    current_all_qa = [
                                        ScreeningQA(
                                            question=item.get("question", ""),
                                            answer=item.get("answer", ""),
                                            category=item.get("category", ""),
                                            created_at=item.get("timestamp", "")
                                        )
                                        for item in opp_qa_list
                                    ] + [new_qa_obj]

                                    doc_result = drive_adapter.create_screening_questions_doc(
                                        folder_id=folder_target_id,
                                        company_name=comp,
                                        job_title=title,
                                        qa_items=current_all_qa,
                                        opportunity_id=opp_id
                                    )
                                    if doc_result and doc_result.get("file_link"):
                                        gdoc_url = doc_result["file_link"]
                                        if storage_adapter.is_connected and hasattr(storage_adapter, "update_opportunity_screening_doc"):
                                            storage_adapter.update_opportunity_screening_doc(
                                                opportunity_id=opp_id,
                                                gdoc_link=gdoc_url,
                                                qa_count=len(current_all_qa)
                                            )

                                st.success(f"Saved screening question to Google Sheets{' and updated Screening Questions Google Doc in Drive!' if gdoc_url else '!'}")
                                if gdoc_url:
                                    st.markdown(f"[📝 Open 'Screening Questions' Google Doc in Drive]({gdoc_url})")
                                if draft_ans_key in st.session_state:
                                    del st.session_state[draft_ans_key]
                                st.rerun()

        # Cross-Job Screening Questions & Answers Library
        st.markdown("---")
        with st.expander("📚 Cross-Job Screening Questions & Answers Library", expanded=False):
            # Reuse in-memory list loaded at top of Tab 2 (0 extra API calls)
            if all_screening_qa:
                sq_search = st.text_input("🔍 Filter Questions by Keyword or Category", placeholder="e.g. dbt, salary, why this company...")
                filtered_qa = all_screening_qa
                if sq_search:
                    filtered_qa = [
                        qa for qa in all_screening_qa
                        if sq_search.lower() in str(qa.get("question", "")).lower()
                        or sq_search.lower() in str(qa.get("answer", "")).lower()
                        or sq_search.lower() in str(qa.get("category", "")).lower()
                    ]
                st.write(f"Found **{len(filtered_qa)}** recorded screening answers:")
                for q_idx, qa in enumerate(reversed(filtered_qa)):
                    q_title = qa.get("question", "Screening Question")
                    q_ans = qa.get("answer", "")
                    q_comp = qa.get("company_name", "")
                    q_cat = qa.get("category", "General")
                    q_time = qa.get("timestamp", "")
                    with st.expander(f"[{q_cat}] {q_title} ({q_comp})"):
                        st.write(f"**Answer:**\n{q_ans}")
                        st.caption(f"Submitted for: {q_comp} on {q_time}")
                        st.code(q_ans, language="text")
            else:
                st.info("No screening questions recorded yet. Add them when ingesting a job in Tab 1!")
    else:
        st.info("No applications found in Google Sheets yet. Paste a job description in Tab 1 to track your first role!")


# =====================================================================
# TAB 3: INTEGRATIONS & EXPANSION (PLACEHOLDERS & ROADMAP)
# =====================================================================
with tab3:
    st.subheader("🔮 Planned Integrations & Future Modules")
    st.caption("These secondary integrations have clean architectural adapters built and are ready to be plugged in when you're ready.")

    col_int1, col_int2 = st.columns(2)

    with col_int1:
        st.markdown("""
        <div class="metric-card">
            <h3 style="color:#60A5FA; margin-top:0;">📞 Twilio Phone Screen Assistant</h3>
            <p><b>Status:</b> 🟡 Simulation Mode (Adapter Staged)</p>
            <p><b>Purpose:</b> Sends real-time SMS alerts with 10-second recall cards before recruiter phone calls and simulates call transcript capture.</p>
            <p><b>Activation Requirements:</b></p>
            <ul>
                <li><code>TWILIO_ACCOUNT_SID</code></li>
                <li><code>TWILIO_AUTH_TOKEN</code></li>
                <li><code>TWILIO_PHONE_NUMBER</code></li>
            </ul>
            <p><i>Code adapter ready at: <code>job_pipeline/adapters/secondary/twilio_adapter.py</code></i></p>
        </div>
        """, unsafe_allow_html=True)

    with col_int2:
        st.markdown("""
        <div class="metric-card">
            <h3 style="color:#34D399; margin-top:0;">✉️ Inbound Email & Job Alert Ingestion</h3>
            <p><b>Status:</b> 🟡 Adapter Prototype Staged</p>
            <p><b>Purpose:</b> Connects to your email to auto-extract incoming job alert emails from LinkedIn, Indeed, and ZipRecruiter directly into your pipeline.</p>
            <p><b>Activation Requirements:</b></p>
            <ul>
                <li>Google Workspace Gmail API or IMAP Credentials</li>
                <li><code>GMAIL_CLIENT_SECRET</code> or App Password</li>
            </ul>
            <p><i>Code adapter ready at: <code>job_pipeline/adapters/secondary/gmail_adapter.py</code></i></p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### ⚙️ Candidate Guardrails & Scoring Profile")
    prof = st.session_state.profile
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.write(f"**Target Compensation Floor**: ${prof.minimum_compensation_floor:,.0f}")
        st.write(f"**Target Pay Percentiles**: {int(prof.target_pay_percentiles[0]*100)}% – {int(prof.target_pay_percentiles[1]*100)}%")
        st.write(f"**Dealbreaker Tech Stack**: {', '.join(prof.dealbreaker_skills)}")
    with col_p2:
        st.write(f"**Core Strengths**: {', '.join(prof.core_strengths)}")
