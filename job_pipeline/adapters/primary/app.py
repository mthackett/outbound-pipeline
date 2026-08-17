import os
import sys
from pathlib import Path

# Ensure project root is in sys.path for Streamlit
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from datetime import datetime

# Set page config as very first Streamlit command
st.set_page_config(
    page_title="GTM Role Intelligence & Pipeline CRM",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

from job_pipeline.domain.models import (
    CandidateProfile, StakeholderContact, Touchpoint, Company, JobPosting, FitEvaluation
)
from job_pipeline.domain.services import JobQualificationService
from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter
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

# Custom CSS styling for premium look & feel
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #F8FAFC;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #94A3B8;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #1E293B;
        border-radius: 10px;
        padding: 1.2rem;
        border: 1px solid #334155;
        margin-bottom: 1rem;
    }
    .target-pay-box {
        background: linear-gradient(135deg, #1E1B4B 0%, #312E81 100%);
        border: 1px solid #6366F1;
        border-radius: 10px;
        padding: 1.2rem;
        color: #EEF2FF;
        margin-bottom: 1.2rem;
    }
    .recall-card {
        background-color: #0F172A;
        border-left: 5px solid #10B981;
        padding: 1.2rem;
        border-radius: 8px;
        margin-top: 1rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# Initialize Session State Objects
if "profile" not in st.session_state:
    st.session_state.profile = CandidateProfile()

if "contacts" not in st.session_state:
    st.session_state.contacts = [
        StakeholderContact(
            contact_id="c1",
            name="Sarah Jenkins",
            company_name="Planful",
            role_type="Recruiter",
            email="sjenkins@planful.com",
            phone_number="+14155550199",
            notes="Initial phone screen scheduled. Focused on ARR metrics and sales forecasting."
        )
    ]

if "touchpoints" not in st.session_state:
    st.session_state.touchpoints = [
        Touchpoint(
            touchpoint_id="t1",
            opportunity_id="opp1",
            channel="Call Transcript",
            direction="Inbound",
            summary="10-min phone screen with Sarah Jenkins. Discussed Planful GTM expansion and $125k-$130k target pay bounds.",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    ]


# Sidebar Configuration
st.sidebar.image("https://img.icons8.com/color/96/briefcase.png", width=64)
st.sidebar.title("Pipeline Controls")

demo_mode = st.sidebar.checkbox("Zero-Cost Demo Mode", value=False, help="Uses mock fixtures and bypasses live API charges.")

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

st.sidebar.markdown("---")
st.sidebar.subheader("🔌 Connection Status")
st.sidebar.write(f"**Sheets API**: {'🟢 Connected' if storage_adapter.is_connected else '🔴 Offline/Demo'}")
st.sidebar.write(f"**Drive API**:  {'🟢 Connected' if drive_adapter.is_connected else '🔴 Offline/Demo'}")
st.sidebar.write(f"**Twilio API**: {'🟢 Connected' if twilio_adapter.is_connected else '🟡 Simulation'}")

st.sidebar.markdown("---")
st.sidebar.caption("GTM Pipeline & Role Intelligence Engine v1.0")


# Main Dashboard Header
st.markdown('<div class="main-title">GTM Role Intelligence & Pipeline CRM</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Consultative evaluation, 60%-80% target salary bounds, 10-second recall cards, and recruiter CRM</div>', unsafe_allow_html=True)


# Main Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 Role Intelligence & Evaluator",
    "📊 Pipeline & Sheets Batch",
    "🏢 Lightweight CRM & Contacts",
    "📞 Twilio & Call Transcripts"
])


# =====================================================================
# TAB 1: ROLE INTELLIGENCE & SINGLE JOB EVALUATOR
# =====================================================================
with tab1:
    st.subheader("Single Job Description Evaluator")

    col_input_1, col_input_2 = st.columns([1, 1])

    with col_input_1:
        company_input = st.text_input("Company Name", value="Planful")
        title_input = st.text_input("Job Title", value="Sales Operations Analyst")
        title_family_input = st.selectbox(
            "Title Family",
            ["revenue_operations", "revenue_systems", "business_analytics", "gtm_engineering", "solutions_implementation"]
        )

    with col_input_2:
        min_pay_input = st.number_input("Posted Min Salary ($)", value=110000, step=5000)
        max_pay_input = st.number_input("Posted Max Salary ($)", value=135000, step=5000)

    jd_text_input = st.text_area(
        "Paste Raw Job Description",
        height=220,
        placeholder="Paste full job description text here..."
    )

    if st.button("⚡ Evaluate Job Posting & Generate Report", type="primary", use_container_width=True):
        if not jd_text_input or len(jd_text_input.strip()) < 20:
            st.error("Please paste a valid job description (at least 20 characters).")
        else:
            with st.spinner("Extracting telemetry, evaluating fit guardrails, and rendering report..."):
                # 0. Telemetry Extraction
                if not demo_mode and isinstance(llm_adapter, OpenAIEngineAdapter):
                    try:
                        telemetry = llm_adapter.extract_job_telemetry(jd_text_input)
                        req_skills = telemetry.requirements.required_tech_stack
                        pref_skills = telemetry.requirements.preferred_tech_stack
                    except Exception:
                        req_skills, pref_skills = [], []
                else:
                    req_skills = ["Salesforce", "SQL", "Tableau", "Power BI", "Clari"]
                    pref_skills = ["Territory Planning", "Gong"]

                # 1. Fit Evaluation
                fit_eval = JobQualificationService.evaluate(
                    company_name=company_input,
                    job_title=title_input,
                    raw_description=jd_text_input,
                    required_skills=req_skills,
                    preferred_skills=pref_skills,
                    salary_min=min_pay_input,
                    salary_max=max_pay_input,
                    profile=st.session_state.profile
                )

                # 2. Select Resume
                selected_resume = resume_repo.select_best_fit_resume(title_input, title_family_input)
                resume_name = selected_resume.filename if selected_resume else "Default Resume"

                # 3. Create Drive Workspace
                workspace = drive_adapter.create_application_workspace(company_input, title_input)
                folder_id = workspace.get("folder_id")
                folder_link = workspace.get("folder_link")

                # 4. Generate Report
                docx_filename = f"{company_input.replace(' ', '_')}_Role_Intelligence_Report.docx"
                output_docx_path = f"output_reports/{docx_filename}"
                os.makedirs("output_reports", exist_ok=True)

                report = llm_adapter.generate_role_intelligence_report(
                    job_data={"company": company_input, "title": title_input, "description": jd_text_input},
                    resume_data={"resume_id": selected_resume.doc_id if selected_resume else "res1", "text": "Resume text"},
                    output_docx_path=output_docx_path,
                    target_pay_bounds=fit_eval.pay_bounds.model_dump(),
                    demo_mode=demo_mode
                )

                # Save to Drive and Sheets
                drive_jd_link = None
                if folder_id:
                    res_jd = drive_adapter.upload_raw_job_description(folder_id, jd_text_input)
                    if isinstance(res_jd, dict):
                        drive_jd_link = res_jd.get("file_link")
                    if selected_resume and selected_resume.doc_id:
                        drive_adapter.export_resume_pdf(selected_resume.doc_id, folder_id, f"{resume_name}.pdf")
                    if os.path.exists(output_docx_path):
                        drive_adapter.upload_role_intelligence_report(folder_id, output_docx_path)

                import uuid
                tot_tokens = getattr(llm_adapter, "last_telemetry_tokens", 0) + getattr(llm_adapter, "last_report_tokens", 0)
                job_posting = JobPosting(
                    opportunity_id=str(uuid.uuid4()),
                    company_name=company_input,
                    job_title=title_input,
                    title_family=title_family_input,
                    raw_description=jd_text_input,
                    required_skills=req_skills,
                    preferred_skills=pref_skills,
                    selected_resume_name=resume_name,
                    drive_folder_link=folder_link,
                    drive_jd_link=drive_jd_link,
                    tokens_used=tot_tokens
                )
                storage_adapter.save_opportunity(job_posting, fit_eval)

                # Render Results UI
                st.success("Evaluation & Report Generation Complete!")

                # Status Badges
                res_col1, res_col2, res_col3 = st.columns(3)
                with res_col1:
                    status_color = "🟢" if fit_eval.status == "PASS" else "🔴"
                    st.metric("Fit Guardrail Status", f"{status_color} {fit_eval.status}")
                with res_col2:
                    st.metric("Skill Match Score", f"{int(fit_eval.fit_score * 100)}%")
                with res_col3:
                    st.metric("Selected Resume", resume_name.replace(".docx", ""))

                # Target Pay Box (60%-80% formula)
                st.markdown(f"""
                <div class="target-pay-box">
                    <h4 style="margin:0; color:#C7D2FE;">💰 Target Salary Range (60% - 80% Percentiles)</h4>
                    <h2 style="margin:5px 0; color:#FFFFFF;">{fit_eval.pay_bounds.display_range}</h2>
                    <p style="margin:0; font-size:0.9rem; color:#A5B4FC;">Formula: Posted Min (${fit_eval.pay_bounds.posted_min:,.0f}) + 60%-80% of Spread (${(fit_eval.pay_bounds.posted_max - fit_eval.pay_bounds.posted_min):,.0f})</p>
                </div>
                """, unsafe_allow_html=True)

                # 10-Second Phone Screen Recall Card
                st.markdown(f"""
                <div class="recall-card">
                    <h3 style="margin:0 0 10px 0; color:#10B981;">📞 10-Second Recruiter Phone Screen Recall Card</h3>
                    <p><b>Company:</b> {company_input} | <b>Role:</b> {title_input}</p>
                    <p><b>Target Compensation Strategy:</b> Anchor at <b>${fit_eval.pay_bounds.target_min:,.0f} - ${fit_eval.pay_bounds.target_max:,.0f}</b> base.</p>
                    <p><b>Matched Resume:</b> {resume_name}</p>
                    <p><b>Key Match Strengths:</b> {', '.join(req_skills[:4]) if req_skills else 'Salesforce, SQL, RevOps, dbt'}</p>
                    <p><b>Drive Folder:</b> <a href="{folder_link}" target="_blank">{folder_link}</a></p>
                </div>
                """, unsafe_allow_html=True)

                # Download Button for DOCX Report
                if os.path.exists(output_docx_path):
                    with open(output_docx_path, "rb") as docx_file:
                        st.download_button(
                            label="📄 Download 2-Page Role Intelligence Report (.docx)",
                            data=docx_file,
                            file_name=docx_filename,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            type="primary"
                        )


# =====================================================================
# TAB 2: PIPELINE & SHEETS BATCH
# =====================================================================
with tab2:
    st.subheader("Google Sheets Pipeline Sync")

    if st.button("🔄 Sync & Process Pending Jobs from Google Sheets", type="primary"):
        with st.spinner("Fetching pending rows from Google Sheets..."):
            pending = storage_adapter.fetch_pending_jobs()
            st.info(f"Found {len(pending)} pending job postings to evaluate.")

            for job in pending:
                st.write(f"Processing: **{job.company_name} - {job.job_title}**")
                fit_eval = JobQualificationService.evaluate(
                    company_name=job.company_name,
                    job_title=job.job_title,
                    raw_description=job.raw_description,
                    profile=st.session_state.profile
                )
                selected_res = resume_repo.select_best_fit_resume(job.job_title, job.title_family)
                job.selected_resume_name = selected_res.filename if selected_res else "Default Resume"

                workspace = drive_adapter.create_application_workspace(job.company_name, job.job_title)
                job.drive_folder_link = workspace.get("folder_link")

                if workspace.get("folder_id"):
                    res_jd = drive_adapter.upload_raw_job_description(workspace["folder_id"], job.raw_description)
                    if isinstance(res_jd, dict):
                        job.drive_jd_link = res_jd.get("file_link")

                storage_adapter.save_opportunity(job, fit_eval)
            st.success("Batch pipeline completed!")


# =====================================================================
# TAB 3: LIGHTWEIGHT CRM & CONTACTS
# =====================================================================
with tab3:
    st.subheader("Lightweight Job Search CRM")

    crm_col1, crm_col2 = st.columns([1, 2])

    with crm_col1:
        st.markdown("### Add Stakeholder Contact")
        c_name = st.text_input("Contact Name", value="Sarah Jenkins")
        c_company = st.text_input("Company", value="Planful")
        c_role = st.selectbox("Role Type", ["Recruiter", "Hiring Manager", "Peer", "VP / Executive"])
        c_email = st.text_input("Email", value="sjenkins@planful.com")
        c_phone = st.text_input("Phone Number", value="+14155550199")
        c_notes = st.text_area("Notes", value="Initial recruiter phone screen scheduled.")

        if st.button("➕ Save Contact to CRM"):
            new_c = StakeholderContact(
                contact_id=str(len(st.session_state.contacts) + 1),
                name=c_name,
                company_name=c_company,
                role_type=c_role,
                email=c_email,
                phone_number=c_phone,
                notes=c_notes
            )
            st.session_state.contacts.append(new_c)
            twilio_adapter.register_contact(new_c)
            st.success(f"Saved contact '{c_name}'!")

    with crm_col2:
        st.markdown("### Registered Contacts & Companies")
        for contact in st.session_state.contacts:
            with st.expander(f"👤 {contact.name} ({contact.company_name}) - {contact.role_type}"):
                st.write(f"**Email**: {contact.email or 'N/A'}")
                st.write(f"**Phone**: {contact.phone_number or 'N/A'}")
                st.write(f"**Notes**: {contact.notes or 'None'}")


# =====================================================================
# TAB 4: TWILIO & CALL TRANSCRIPTS
# =====================================================================
with tab4:
    st.subheader("Twilio Voice & SMS Intelligence")

    tw_col1, tw_col2 = st.columns([1, 1])

    with tw_col1:
        st.markdown("### Send Recruiter SMS")
        sms_to = st.text_input("Recruiter Phone Number", value="+14155550199")
        sms_body = st.text_area("SMS Body", value="Hi Sarah, following up regarding the Sales Operations Analyst role at Planful. Looking forward to our call!")

        if st.button("📱 Send Twilio SMS", type="primary"):
            res = twilio_adapter.send_sms(sms_to, sms_body)
            if res:
                st.success(f"SMS dispatched to {sms_to}!")

    with tw_col2:
        st.markdown("### Ingest Recruiter Call Transcript")
        call_sid = st.text_input("Call SID", value="CA1234567890abcdef")
        transcript_text = st.text_area(
            "Paste Call Transcript / Notes",
            value="Recruiter: Hi! We're offering $110k-$135k base. Candidate: Great, my target range is $125k-$130k base based on my RevOps and dbt experience."
        )

        if st.button("🎙️ Summarize Call Transcript"):
            tp = twilio_adapter.ingest_call_transcript(call_sid, transcript_text)
            st.session_state.touchpoints.append(tp)
            st.success("Call transcript summarized!")
            st.info(f"**Summary**: {tp.summary}")
