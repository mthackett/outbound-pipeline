import os
import re
import sys
import uuid
from typing import List, Dict, Any, Optional
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
    CandidateProfile, JobPosting, FitEvaluation, StakeholderContact, Touchpoint, ScreeningQA, QuickLink,
    SCREENING_CATEGORIES, SCREENING_ARCHETYPES, StoryBreadcrumb, CanonicalStory, StoryCueCard, ScreeningMatchResult
)
from job_pipeline.domain.services import (
    JobQualificationService, ApplicationGuardrailService, ScreeningQAService, QuickLinksService,
    ScreeningIntelligenceService, StoryBankService
)
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
    .story-box {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1.0rem;
    }
    .cue-card-box {
        background: #111827;
        border: 1px solid #374151;
        border-left: 4px solid #6366F1;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.8rem;
    }
    .breadcrumb-step {
        display: inline-block;
        background: #1F2937;
        border: 1px solid #374151;
        border-radius: 6px;
        padding: 0.4rem 0.7rem;
        margin-right: 0.4rem;
        margin-bottom: 0.4rem;
        font-size: 0.82rem;
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

if "quicklinks" not in st.session_state:
    st.session_state.quicklinks = QuickLinksService.load_quicklinks()

if "story_bank" not in st.session_state:
    st.session_state.story_bank = StoryBankService.load_stories()

if "active_opp_card" not in st.session_state:
    st.session_state.active_opp_card = None

if "active_sub_card" not in st.session_state:
    st.session_state.active_sub_card = None


def render_breadcrumb_trail(breadcrumbs: List[StoryBreadcrumb]):
    """
    Renders breadcrumb milestones prominently as the primary visual for phone/Zoom recall.
    Displays bold step numbers, distinct category tags, and high-visibility soundbite taglines.
    """
    if not breadcrumbs:
        return

    color_palette = [
        ("#818CF8", "#1E1B4B"),  # Indigo
        ("#F59E0B", "#451A03"),  # Amber
        ("#38BDF8", "#082F49"),  # Sky
        ("#34D399", "#064E3B"),  # Emerald
        ("#EC4899", "#500724"),  # Pink
        ("#A78BFA", "#2E1065"),  # Purple
    ]

    cols = st.columns(len(breadcrumbs))
    for idx, (col, b) in enumerate(zip(cols, breadcrumbs)):
        accent_color, bg_tint = color_palette[idx % len(color_palette)]
        with col:
            st.markdown(f"""
            <div style="background:{bg_tint}; border:2px solid {accent_color}; border-radius:10px; padding:12px 14px; min-height:110px; margin-bottom:10px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="color:{accent_color}; font-weight:800; font-size:0.86rem; letter-spacing:0.6px; text-transform:uppercase;">
                        {idx + 1}. {b.label}
                    </span>
                    <span style="font-size:0.72rem; background:{accent_color}33; color:{accent_color}; padding:2px 6px; border-radius:4px; font-weight:700;">
                        {b.kind.upper()}
                    </span>
                </div>
                <div style="color:#FFFFFF; font-size:0.92rem; font-weight:600; line-height:1.4;">
                    {b.content}
                </div>
            </div>
            """, unsafe_allow_html=True)


def render_quicklinks_manager(context_key: str = "sb"):
    """Interactive editor to add, update, remove, and reset candidate quicklinks."""
    current_links = list(st.session_state.quicklinks)

    st.markdown("##### ⚙️ Configured Links:")
    for idx, link in enumerate(current_links):
        with st.expander(f"{link.icon} {link.title}", expanded=False):
            with st.form(key=f"{context_key}_edit_form_{link.id}_{idx}"):
                ed_title = st.text_input("Title / Label", value=link.title, key=f"{context_key}_t_{link.id}_{idx}")
                ed_url = st.text_input("URL", value=link.url, key=f"{context_key}_u_{link.id}_{idx}")
                c_icon, c_cat = st.columns([1, 2])
                with c_icon:
                    ed_icon = st.text_input("Icon", value=link.icon, max_chars=4, key=f"{context_key}_i_{link.id}_{idx}")
                with c_cat:
                    cat_options = ["Profile", "Portfolio", "Calendar", "Other"]
                    c_idx = cat_options.index(link.category) if link.category in cat_options else 0
                    ed_cat = st.selectbox("Category", cat_options, index=c_idx, key=f"{context_key}_c_{link.id}_{idx}")

                btn_update = st.form_submit_button("💾 Update Link")
                if btn_update:
                    if ed_title.strip() and ed_url.strip():
                        current_links[idx] = QuickLink(
                            id=link.id,
                            title=ed_title.strip(),
                            url=ed_url.strip(),
                            category=ed_cat,
                            icon=ed_icon.strip() or "🔗"
                        )
                        QuickLinksService.save_quicklinks(current_links)
                        st.session_state.quicklinks = current_links
                        st.success(f"Updated '{ed_title}'!")
                        st.rerun()
                    else:
                        st.warning("Title and URL cannot be empty.")

            if st.button("🗑️ Delete Link", key=f"{context_key}_del_{link.id}_{idx}"):
                current_links.pop(idx)
                QuickLinksService.save_quicklinks(current_links)
                st.session_state.quicklinks = current_links
                st.success(f"Deleted {link.title}!")
                st.rerun()

    st.markdown("---")
    st.markdown("##### ➕ Add New Quicklink:")
    with st.form(key=f"{context_key}_add_form", clear_on_submit=True):
        new_title = st.text_input("Title / Label", placeholder="e.g. Substack or Personal Blog")
        new_url = st.text_input("URL", placeholder="https://...")
        c_n_icon, c_n_cat = st.columns([1, 2])
        with c_n_icon:
            new_icon = st.text_input("Icon Emoji", value="🔗", max_chars=4)
        with c_n_cat:
            new_cat = st.selectbox("Category", ["Profile", "Portfolio", "Calendar", "Other"], key=f"{context_key}_new_cat")

        btn_add = st.form_submit_button("➕ Add Quicklink")
        if btn_add:
            if new_title.strip() and new_url.strip():
                new_item = QuickLink(
                    title=new_title.strip(),
                    url=new_url.strip(),
                    category=new_cat,
                    icon=new_icon.strip() or "🔗"
                )
                current_links.append(new_item)
                QuickLinksService.save_quicklinks(current_links)
                st.session_state.quicklinks = current_links
                st.success(f"Added '{new_item.title}'!")
                st.rerun()
            else:
                st.warning("Please provide both a Title and a URL.")

    if st.button("🔄 Reset to Default Links", key=f"{context_key}_reset_btn", help="Resets your quicklinks list to the default setup"):
        defaults = QuickLinksService.get_default_quicklinks()
        QuickLinksService.save_quicklinks(defaults)
        st.session_state.quicklinks = defaults
        st.info("Reset to default quicklinks.")
        st.rerun()



# Sidebar Configuration & Connections
st.sidebar.image("https://img.icons8.com/color/96/briefcase.png", width=56)
st.sidebar.title("Pipeline Controls")

demo_mode = st.sidebar.checkbox(
    "Zero-Cost Demo Mode",
    value=os.environ.get("DEMO_MODE", "false").lower() == "true",
    help="Uses mock fixtures and bypasses live API charges."
)

@st.cache_resource
def get_adapters(is_demo: bool):
    if is_demo:
        storage = MockJobStorageAdapter()
        drive = MockDocumentStorageAdapter()
        resume = MockResumeRepositoryAdapter()
        llm = MockLLMStrategyAdapter()
        twilio = TwilioMessagingAdapter()
    else:
        storage = GoogleSheetsAdapter()
        drive = GoogleDriveAdapter()
        resume = drive
        llm = OpenAIEngineAdapter()
        twilio = TwilioMessagingAdapter()

    gmail = GmailIngestionAdapter()
    return storage, drive, resume, llm, twilio, gmail

storage_adapter, drive_adapter, resume_repo, llm_adapter, twilio_adapter, gmail_adapter = get_adapters(demo_mode)

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

# Candidate Application Quicklinks Area
st.sidebar.markdown("---")
st.sidebar.subheader("⚡ Candidate Quicklinks")
with st.sidebar.expander("📋 Fast Application Links", expanded=True):
    st.caption("Hover over titles to view URLs, or click to open:")
    for q_link in st.session_state.quicklinks:
        st.markdown(
            f'<div title="{q_link.url}" style="font-weight: 600; font-size: 0.95rem; margin-bottom: 2px; cursor: default;">{q_link.icon} {q_link.title}</div>',
            unsafe_allow_html=True,
            help=q_link.url
        )
        st.link_button(f"↗ Open {q_link.title}", q_link.url, use_container_width=True, help=q_link.url)
        st.write("")

    bundle_text = QuickLinksService.format_clipboard_bundle(st.session_state.quicklinks)
    with st.expander("📋 Copy All Links (Bundle)", expanded=False):
        st.caption("All links formatted together:")
        st.code(bundle_text, language=None)

    with st.expander("⚙️ Configure Quicklinks", expanded=False):
        render_quicklinks_manager(context_key="sb")

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


# Main Tabs: Focused on Ingestion, Live Pipeline CRM, Global Story Bank, and Expansion
tab1, tab2, tab3, tab4 = st.tabs([
    "⚡ Fast Ingestion & Apply Kit",
    "📊 Pipeline Tracker & CRM",
    "📖 Global Story Bank & Interview Map",
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

        # Load historical screening QA for similarity recall
        historical_qa = storage_adapter.fetch_screening_qa() if storage_adapter.is_connected else []

        screening_inputs = []
        for i in range(st.session_state.num_screening_qa):
            st.markdown(f"---")
            st.markdown(f"**Screening Question {i + 1}**")
            cq1, cq2 = st.columns([3, 1])
            with cq1:
                q_text = st.text_input(f"Question Prompt", key=f"sq_q_{i}", placeholder="e.g. Describe your experience with Salesforce & dbt.")
            with cq2:
                q_cat = st.selectbox(f"Category", SCREENING_CATEGORIES, key=f"sq_cat_{i}")

            # Screening Question Intelligence: Archetype & Recall
            q_arch = "GENERAL"
            q_signals = []
            if q_text and q_text.strip():
                q_arch = ScreeningIntelligenceService.classify_archetype(q_text)
                q_signals = ScreeningIntelligenceService.extract_competency_signals(q_text)

                c_info1, c_info2 = st.columns([2, 1])
                with c_info1:
                    if q_signals:
                        pills = " ".join([f'<span class="badge-pill" style="background:#1E3A8A; color:#BFDBFE; font-size:0.75rem;">{s}</span>' for s in q_signals])
                        st.markdown(f"<b>Competencies Detected:</b> {pills}", unsafe_allow_html=True)
                with c_info2:
                    st.caption(f"Archetype: `{SCREENING_ARCHETYPES.get(q_arch, q_arch)}`")

                # Prior-answer similarity check
                sim_matches = ScreeningIntelligenceService.find_similar_questions(q_text, historical_qa, threshold=0.38)
                if sim_matches:
                    top_m = sim_matches[0]
                    st.info(
                        f"💡 **Similar Past Question Found ({int(top_m.similarity_score * 100)}% match)**\n\n"
                        f"*Prior Question:* \"{top_m.matched_question}\" ({top_m.company_name or 'Past Role'})\n\n"
                        f"**Prior Answer:** {top_m.matched_answer}"
                    )
                    if st.button(f"📋 Use Prior Answer for Question {i + 1}", key=f"btn_recall_qa_{i}"):
                        st.session_state[f"sq_a_{i}"] = top_m.matched_answer
                        if top_m.archetype == "COMPENSATION":
                            st.session_state[f"sq_cat_{i}"] = "Salary"
                        elif top_m.archetype == "TECHNICAL_STACK":
                            st.session_state[f"sq_cat_{i}"] = "Technical"
                        elif top_m.archetype == "EXPERIENCE_DOMAIN":
                            st.session_state[f"sq_cat_{i}"] = "Experience"
                        elif top_m.archetype == "QUESTIONS_FOR_COMPANY":
                            st.session_state[f"sq_cat_{i}"] = "Questions for Company"
                        st.rerun()

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
                screening_inputs.append(ScreeningQA(
                    question=q_text,
                    answer=ans_text,
                    category=q_cat,
                    archetype=q_arch,
                    competency_signals=q_signals
                ))

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
        if pb.target_min is not None and pb.target_max is not None:
            form_advice = f"Anchor at <b>${pb.target_min:,.0f}</b> or enter range <b>${pb.target_min:,.0f} – ${pb.target_max:,.0f}</b>."
            if pb.posted_min is not None and pb.posted_max is not None:
                form_advice += f" (Calculated from posted base spread: ${pb.posted_min:,.0f} – ${pb.posted_max:,.0f})"
            comp_strategy = f"Anchor base at <b>${pb.target_min:,.0f} – ${pb.target_max:,.0f}</b>."
        elif pb.target_min is not None:
            form_advice = f"Anchor at <b>${pb.target_min:,.0f}+</b>."
            comp_strategy = f"Anchor base at <b>${pb.target_min:,.0f}+</b>."
        elif pb.target_max is not None:
            form_advice = f"Anchor up to <b>${pb.target_max:,.0f}</b>."
            comp_strategy = f"Anchor base up to <b>${pb.target_max:,.0f}</b>."
        else:
            floor_val = st.session_state.profile.minimum_compensation_floor
            form_advice = f"Base compensation undisclosed in job posting. Propose candidate floor <b>${floor_val:,.0f}+</b> or enter <i>'Competitive / Negotiable'</i>."
            comp_strategy = f"Undisclosed (Target floor: <b>${floor_val:,.0f}+</b> or align with recruiter on screen)."

        st.markdown(f"""
        <div class="target-pay-box">
            <h4 style="margin:0; color:#C7D2FE;">💰 Desired Salary Answer (60% – 80% Target Anchor)</h4>
            <h2 style="margin:6px 0; color:#FFFFFF; font-weight:800;">{pb.display_range}</h2>
            <p style="margin:0; font-size:0.92rem; color:#A5B4FC;">
                <b>For application form:</b> {form_advice}
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Quick Candidate Profile Links for Application Form
        with st.expander("⚡ Candidate Profile Quicklinks (1-Click Copy for ATS)", expanded=False):
            st.caption("Quickly grab your profile links to paste into this application form:")
            ak_cols = st.columns(min(len(st.session_state.quicklinks), 4) or 1)
            for q_idx, q_link in enumerate(st.session_state.quicklinks):
                with ak_cols[q_idx % len(ak_cols)]:
                    st.markdown(f"**{q_link.icon} {q_link.title}**")
                    st.code(q_link.url, language=None)
                    st.link_button("↗ Open", q_link.url, use_container_width=True)

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
            <p style="margin:4px 0;"><b>Compensation Strategy:</b> {comp_strategy}</p>
            <p style="margin:4px 0;"><b>Core Pain Points:</b> {ev.get('pain_points') or 'Scaling revenue reporting, pipeline velocity, and cross-functional visibility.'}</p>
            <p style="margin:4px 0;"><b>Required Skills Highlight:</b> {', '.join(ev.get('req_skills', [])[:5]) or 'Salesforce, SQL, RevOps, dbt'}</p>
        </div>
        """, unsafe_allow_html=True)

        # Targeted Interview Story Cue Cards for this Role
        suggested_cues = StoryBankService.suggest_story_cue_cards(
            job_text=ev.get("pain_points", "") + " " + " ".join(ev.get("req_skills", [])),
            req_skills=ev.get("req_skills", []),
            pain_points=ev.get("pain_points", ""),
            role_family=ev.get("family", ""),
            top_k=3
        )
        if suggested_cues:
            with st.expander(f"📖 Targeted Behavioral Story Cue Cards for this Role ({len(suggested_cues)})", expanded=True):
                st.caption("When behavioral questions arise during recruiter screens or interviews, anchor on these canonical stories:")
                for sc in suggested_cues:
                    st.markdown(f"""
                    <div class="cue-card-box">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 style="margin:0; color:#818CF8;">📖 Story {sc.story_number}: {sc.title}</h4>
                            <span class="badge-pill" style="background:#312E81; color:#C7D2FE; font-weight:700;">{sc.recommended_angle}</span>
                        </div>
                        <p style="margin:4px 0 8px 0; font-size:0.88rem; color:#94A3B8;"><b>Match Signal:</b> <i>{sc.relevance_reason}</i></p>
                    </div>
                    """, unsafe_allow_html=True)
                    if sc.active_breadcrumbs:
                        render_breadcrumb_trail(sc.active_breadcrumbs)
                    c_sc1, c_sc2 = st.columns(2)
                    with c_sc1:
                        st.markdown(f"**⚡ The Turning Point:** {sc.turning_point}")
                    with c_sc2:
                        st.markdown(f"**📊 Proven Result:** <span style='color:#34D399; font-weight:600;'>{sc.result}</span>", unsafe_allow_html=True)
                    with st.expander(f"🎯 Questions Story {sc.story_number} Answers", expanded=False):
                        for q_item in sc.target_question_types:
                            st.write(f"• {q_item}")

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

            is_card_open = (st.session_state.get("active_opp_card") == opp_id)
            with st.expander(f"{s_icon} **{comp}** — {title}  |  *Status:* `{curr_status}`  |  *Pay:* `{target_pay}`", expanded=is_card_open):
                c_card1, c_card2 = st.columns([1, 1])

                with c_card1:
                    st.write(f"**Date Created**: {date_added or 'Recent'}")
                    st.markdown(f"**Target Pay**: `{target_pay or 'Not calculated'}`")
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
                        st.session_state.active_opp_card = opp_id
                        st.session_state.active_sub_card = None
                        if storage_adapter.is_connected:
                            success = storage_adapter.update_opportunity_status(opp_id, new_stage, new_notes)
                            if success:
                                opp["Status"] = new_stage
                                opp["Notes"] = new_notes
                                st.success(f"Updated {comp} to '{new_stage}' in Google Sheets!")
                                st.rerun()
                            else:
                                st.error("Failed to update status in Google Sheets.")
                        else:
                            opp["Status"] = new_stage
                            opp["Notes"] = new_notes
                            st.info(f"Simulated update: {comp} set to '{new_stage}' (Demo Mode).")
                            st.rerun()

                # Section: Targeted Behavioral Story Cue Cards for this Role
                app_cues = StoryBankService.suggest_story_cue_cards(
                    job_text=f"{comp} {title} {notes}",
                    req_skills=[title],
                    pain_points=notes,
                    top_k=2
                )
                if app_cues:
                    with st.expander("📖 Interview Story Cue Cards for this Role", expanded=False):
                        st.caption("Anchor phone screens and interview answers on these canonical stories:")
                        for ac in app_cues:
                            st.markdown(f"**Story {ac.story_number}: {ac.title}** (`{ac.recommended_angle}`)")
                            st.caption(f"⚡ *Turning Point:* {ac.turning_point}")
                            st.caption(f"📊 *Result:* {ac.result}")

                # Section A: Structured Call & Interview Logger
                is_call_open = (st.session_state.get("active_opp_card") == opp_id and st.session_state.get("active_sub_card") == f"call_{opp_id}")
                with st.expander("📞 Log Call / Interview Notes", expanded=is_call_open):
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
                            st.session_state.active_opp_card = opp_id
                            st.session_state.active_sub_card = f"call_{opp_id}"
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
                draft_ans_key = f"draft_ans_val_{opp_id}_{idx}"
                is_qa_open = (st.session_state.get("active_opp_card") == opp_id and (st.session_state.get("active_sub_card") == f"qa_{opp_id}" or bool(st.session_state.get(draft_ans_key))))
                with st.expander("📝 Screening Questions & Answers for this Role", expanded=is_qa_open):
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

                    if btn_draft_ai:
                        st.session_state.active_opp_card = opp_id
                        st.session_state.active_sub_card = f"qa_{opp_id}"
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
                    with st.form(key=f"qa_form_{opp_id}_{idx}", clear_on_submit=True):
                        q_new_prompt = st.text_input(
                            "Screening Question Prompt",
                            value=ai_prompt_hint if ai_prompt_hint else "",
                            placeholder="e.g. Describe your experience scaling HubSpot to Salesforce syncs.",
                            key=f"new_q_prompt_{opp_id}_{idx}"
                        )
                        q_new_cat = st.selectbox(
                            "Category",
                            SCREENING_CATEGORIES,
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
                            st.session_state.active_opp_card = opp_id
                            st.session_state.active_sub_card = f"qa_{opp_id}"
                            if not q_new_prompt.strip() or not q_new_ans.strip():
                                st.warning("Please enter both the question and answer.")
                            else:
                                new_qa_obj = ScreeningQA(
                                    question=q_new_prompt.strip(),
                                    answer=q_new_ans.strip(),
                                    category=q_new_cat,
                                    archetype=ScreeningIntelligenceService.classify_archetype(q_new_prompt.strip()),
                                    competency_signals=ScreeningIntelligenceService.extract_competency_signals(q_new_prompt.strip())
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

                                if gdoc_url:
                                    st.success("Saved screening question to Google Sheets and updated Screening Questions Google Doc in Drive!")
                                    st.markdown(f"[📝 Open 'Screening Questions' Google Doc in Drive]({gdoc_url})")
                                else:
                                    st.success("Saved screening question to Google Sheets!")

                                # Clear all screening Q&A inputs so fields return to their default blank state
                                for key_to_clear in [
                                    f"ai_hint_{opp_id}_{idx}",
                                    f"new_q_prompt_{opp_id}_{idx}",
                                    f"new_q_ans_{opp_id}_{idx}",
                                    f"new_q_cat_{opp_id}_{idx}",
                                    draft_ans_key
                                ]:
                                    if key_to_clear in st.session_state:
                                        del st.session_state[key_to_clear]

                                st.rerun()

        # Cross-Job Screening Questions & Answers Library
        st.markdown("---")
        with st.expander("📚 Cross-Job Screening Questions & Answers Library", expanded=False):
            # Reuse in-memory list loaded at top of Tab 2 (0 extra API calls)
            if all_screening_qa:
                col_f1, col_f2 = st.columns([2, 1])
                with col_f1:
                    sq_search = st.text_input("🔍 Filter Questions by Keyword", placeholder="e.g. dbt, salary, why this company...")
                with col_f2:
                    arch_names = ["All Archetypes"] + list(SCREENING_ARCHETYPES.values())
                    selected_arch_filter = st.selectbox("Filter by Question Archetype", arch_names)

                filtered_qa = all_screening_qa
                if sq_search:
                    sq = sq_search.lower()
                    filtered_qa = [
                        qa for qa in filtered_qa
                        if sq in str(qa.get("question", "")).lower()
                        or sq in str(qa.get("answer", "")).lower()
                        or sq in str(qa.get("category", "")).lower()
                    ]
                if selected_arch_filter != "All Archetypes":
                    matched_codes = [k for k, v in SCREENING_ARCHETYPES.items() if v == selected_arch_filter]
                    target_code = matched_codes[0] if matched_codes else ""
                    filtered_qa = [
                        qa for qa in filtered_qa
                        if qa.get("archetype") == target_code
                        or ScreeningIntelligenceService.classify_archetype(qa.get("question", "")) == target_code
                    ]

                st.write(f"Found **{len(filtered_qa)}** recorded screening answers:")
                for q_idx, qa in enumerate(reversed(filtered_qa)):
                    q_title = qa.get("question", "Screening Question")
                    q_ans = qa.get("answer", "")
                    q_comp = qa.get("company_name", "")
                    q_cat = qa.get("category", "General")
                    q_time = qa.get("timestamp", "")
                    q_arch_code = qa.get("archetype") or ScreeningIntelligenceService.classify_archetype(q_title)
                    q_arch_label = SCREENING_ARCHETYPES.get(q_arch_code, "General")
                    q_comps = qa.get("competency_signals") or ScreeningIntelligenceService.extract_competency_signals(q_title)

                    with st.expander(f"[{q_cat} | {q_arch_label}] {q_title} ({q_comp})"):
                        if q_comps:
                            pills_html = "<b>Competency Signals:</b> " + " ".join([f'<span class="badge-pill" style="background:#1E3A8A; color:#BFDBFE; font-size:0.75rem;">{c}</span>' for c in q_comps])
                            st.markdown(pills_html, unsafe_allow_html=True)
                        st.write(f"**Answer:**\n{q_ans}")
                        st.caption(f"Submitted for: {q_comp} on {q_time}")
                        st.code(q_ans, language="text")
            else:
                st.info("No screening questions recorded yet. Add them when ingesting a job in Tab 1!")
    else:
        st.info("No applications found in Google Sheets yet. Paste a job description in Tab 1 to track your first role!")


# =====================================================================
# TAB 3: GLOBAL PROFESSIONAL STORY BANK & INTERVIEW NARRATIVE MAP
# =====================================================================
with tab3:
    st.subheader("📖 Global Professional Story Bank & Interview Narrative Map")
    st.caption("12 canonical behavioral stories grounded in RevOps, GTM Systems, Data Architecture, and Cross-Functional Leadership. Modularized into breadcrumb trails with lock protections.")

    # Always ensure story bank is loaded in session state
    if "story_bank" not in st.session_state or not st.session_state.story_bank:
        st.session_state.story_bank = StoryBankService.load_stories()

    stories = st.session_state.story_bank

    # 1. Behavioral Question Reconnaissance & Routing Tool
    with st.expander("🎯 Behavioral Question Recon & Routing Tool", expanded=True):
        st.caption("Paste or type any interview question to instantly identify the matching canonical story, recommended angle, turning point, and breadcrumbs.")
        c_recon1, c_recon2 = st.columns([3, 1])
        with c_recon1:
            user_b_prompt = st.text_input(
                "Behavioral Question / Interview Prompt",
                placeholder="e.g. Tell me about a time you handled conflict between sales and marketing over lead quality."
            )
        with c_recon2:
            st.write("")
            recon_sample = st.selectbox(
                "Quick Example Prompts",
                [
                    "-- Select Sample --",
                    "Ambiguous data requirements / pipeline leakage",
                    "Sales & marketing lead routing SLA conflict",
                    "Modernizing reporting stack from sheets to dbt",
                    "Persuading leadership with data / attribution dispute",
                    "Technical integration failure / webhook recovery",
                    "High-stakes territory realignment under tight deadline",
                    "Sales rep resistance to CRM process governance",
                    "Balancing board deck fire drill vs broken routing",
                    "Customer churn predictive model & ARR preservation",
                    "Teaching non-technical managers self-serve analytics",
                    "Vendor tech stack audit and cost reduction",
                    "M&A CRM data migration and cutover"
                ]
            )
            if recon_sample != "-- Select Sample --":
                sample_map = {
                    "Ambiguous data requirements / pipeline leakage": "Tell me about a time you handled highly ambiguous data requirements and had to find root cause.",
                    "Sales & marketing lead routing SLA conflict": "How have you resolved operational conflict between sales and marketing teams?",
                    "Modernizing reporting stack from sheets to dbt": "Describe a major technical migration or automated reporting workflow you led.",
                    "Persuading leadership with data / attribution dispute": "Tell me about a time you used data to persuade skeptical executive stakeholders.",
                    "Technical integration failure / webhook recovery": "Tell me about a time something went seriously wrong with a system and how you owned it.",
                    "High-stakes territory realignment under tight deadline": "Describe a high-pressure quantitative project with a firm deadline that you delivered.",
                    "Sales rep resistance to CRM process governance": "Tell me about a time you faced strong user resistance to a new operational process.",
                    "Balancing board deck fire drill vs broken routing": "How do you prioritize when multiple senior executives have competing urgent demands?",
                    "Customer churn predictive model & ARR preservation": "Give an example of an operational project that directly impacted revenue retention.",
                    "Teaching non-technical managers self-serve analytics": "Tell me about a time you mentored or enabled non-technical colleagues on data.",
                    "Vendor tech stack audit and cost reduction": "How do you evaluate software vendors and eliminate tech stack redundancy?",
                    "M&A CRM data migration and cutover": "Describe the most complex database migration or systems cutover you have managed."
                }
                user_b_prompt = sample_map.get(recon_sample, user_b_prompt)

        if user_b_prompt:
            recon_match = StoryBankService.match_behavioral_prompt(user_b_prompt)
            if recon_match:
                matched_s = recon_match["story"]
                st.markdown(f"""
                <div class="cue-card-box" style="border-left:5px solid #10B981; margin-bottom:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <h3 style="margin:0; color:#34D399;">🎯 Matched: Story {matched_s.story_number} — {matched_s.title}</h3>
                        <span class="badge-pill" style="background:#065F46; color:#A7F3D0; font-weight:700;">{recon_match['recommended_angle']}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                if recon_match.get("breadcrumbs"):
                    st.markdown("##### 🍞 Visual Recall Breadcrumb Stepper (Live Call Guide):")
                    render_breadcrumb_trail(recon_match["breadcrumbs"])
                c_rc1, c_rc2 = st.columns(2)
                with c_rc1:
                    st.markdown(f"""
                    <div style="background:#1E293B; border-left:4px solid #6366F1; padding:10px 14px; border-radius:6px; min-height:85px;">
                        <div style="color:#A5B4FC; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">⚡ The Turning Point</div>
                        <div style="color:#F8FAFC; font-size:0.92rem; font-weight:500; margin-top:4px;">{recon_match['turning_point']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c_rc2:
                    st.markdown(f"""
                    <div style="background:#064E3B; border-left:4px solid #10B981; padding:10px 14px; border-radius:6px; min-height:85px;">
                        <div style="color:#6EE7B7; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">📊 Proven Result & Metrics</div>
                        <div style="color:#ECFDF5; font-size:0.92rem; font-weight:600; margin-top:4px;">{recon_match['result']}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No high-confidence match found. Try entering key operational terms like 'SLA', 'SQL', 'conflict', or 'reporting'.")

    # 2. Controls & Search Bar
    st.markdown("---")

    if not stories:
        st.warning("⚠️ **Your Story Bank is currently empty (`stories.json` has no stories or was not found).**")
        if st.button("🌱 Initialize 12 Canonical Stories", type="primary"):
            st.session_state.story_bank = StoryBankService.reset_canonical_stories()
            st.success("Loaded 12 canonical stories into stories.json!")
            st.rerun()

    c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 1, 1])
    with c_ctrl1:
        story_search = st.text_input("🔍 Search Stories by Title, Tool, Keyword, or Turning Point", placeholder="e.g. dbt, Salesforce, SLA, $410K...")
    with c_ctrl2:
        tag_options = ["All Themes", "Ambiguity", "Conflict", "Modern Data Stack", "Influence", "Setback", "Quantitative", "User Adoption", "Prioritization", "Retention", "Enablement", "Cost Optimization", "M&A Integration"]
        selected_tag = st.selectbox("Filter by Theme", tag_options)
    with c_ctrl3:
        st.write("")
        if st.button("🔄 Reset Canonical Seeds", help="Restores the 12 pristine default canonical stories"):
            st.session_state.story_bank = StoryBankService.reset_canonical_stories()
            st.success("Reset story bank to canonical defaults!")
            st.rerun()

    # 2b. Form to Create a New Story from Scratch
    create_exp_expanded = (len(stories) == 0)
    with st.expander("➕ Create New Story from Scratch", expanded=create_exp_expanded):
        st.caption("Author a brand-new professional story with modular visual breadcrumbs. Hitting 'Save Story' will create or update `stories.json`.")
        with st.form("create_new_story_form"):
            c_new1, c_new2 = st.columns([3, 1])
            with c_new1:
                new_title = st.text_input("Story Title *", placeholder="e.g. Cross-Functional Pipeline Metric Alignment")
            with c_new2:
                next_num = len(stories) + 1
                new_num = st.number_input("Story Number", min_value=1, value=next_num, step=1)

            c_meta1, c_meta2 = st.columns(2)
            with c_meta1:
                new_tags = st.text_input("Archetype Tags (comma-separated)", placeholder="e.g. Ambiguity, Root Cause, Process Improvement")
                new_comps = st.text_input("Competency Signals (comma-separated)", placeholder="e.g. SQL, Data Modeling, Stakeholder Alignment")
            with c_meta2:
                new_inds = st.text_input("Target Industries (comma-separated)", placeholder="e.g. B2B SaaS, Technology, Enterprise")
                new_locked = st.checkbox("Lock Story (protect from system rewrites)", value=False)

            st.markdown("##### 📝 Narrative Components:")
            new_hook = st.text_area("Elevator Hook (1-2 sentences for opening answers)", placeholder="e.g. Uncovered $400K in unattributed pipeline by building a row-level lifecycle data model.")
            new_problem = st.text_area("The Problem & Stakes", placeholder="e.g. Sales and marketing leadership reported conflicting numbers, threatening quarterly forecasting.")
            new_tp = st.text_area("The Turning Point (Pivot)", placeholder="e.g. Traced raw audit timestamps in SQL to map the exact end-to-end deal journey.")
            new_result = st.text_area("Measurable Result & Metrics", placeholder="e.g. Discovered orphaned leads; reconciled gap and established trusted forecast baseline.")
            new_learning = st.text_area("Lasting Philosophy / Learning", placeholder="e.g. Trust in reporting starts at the raw event level.")

            st.markdown("##### 🍞 Visual Breadcrumb Milestones (Primary Visual for Calls):")
            st.caption("Define 3-4 concise narrative beats with distinct labels and punchy soundbite taglines.")
            bc_cols = st.columns(4)
            b_kinds = ["context", "action", "pivot", "milestone", "metric"]

            with bc_cols[0]:
                st.markdown("**Milestone 1**")
                b1_label = st.text_input("Step 1 Label", value="The Trigger / Signal", key="new_b1_lbl")
                b1_kind = st.selectbox("Step 1 Kind", b_kinds, index=0, key="new_b1_k")
                b1_content = st.text_area("Step 1 Soundbite", placeholder="The initial problem or spark", key="new_b1_c", height=70)

            with bc_cols[1]:
                st.markdown("**Milestone 2**")
                b2_label = st.text_input("Step 2 Label", value="The Turning Point", key="new_b2_lbl")
                b2_kind = st.selectbox("Step 2 Kind", b_kinds, index=2, key="new_b2_k")
                b2_content = st.text_area("Step 2 Soundbite", placeholder="The technical or tactical pivot", key="new_b2_c", height=70)

            with bc_cols[2]:
                st.markdown("**Milestone 3**")
                b3_label = st.text_input("Step 3 Label", value="The Action", key="new_b3_lbl")
                b3_kind = st.selectbox("Step 3 Kind", b_kinds, index=3, key="new_b3_k")
                b3_content = st.text_area("Step 3 Soundbite", placeholder="The core execution step", key="new_b3_c", height=70)

            with bc_cols[3]:
                st.markdown("**Milestone 4**")
                b4_label = st.text_input("Step 4 Label", value="Hard Result", key="new_b4_lbl")
                b4_kind = st.selectbox("Step 4 Kind", b_kinds, index=4, key="new_b4_k")
                b4_content = st.text_area("Step 4 Soundbite", placeholder="The quantified metric or impact", key="new_b4_c", height=70)

            st.markdown("##### 🎯 Routing & Recon Matching:")
            new_keywords = st.text_input("Trigger Keywords (comma-separated)", placeholder="e.g. ambiguity, discrepancy, reconciliation, root cause")
            new_questions = st.text_area("Target Behavioral Questions (one per line)", placeholder="Tell me about a time you handled ambiguous requirements.\nDescribe a complex problem where you uncovered root cause.")

            submit_new_story = st.form_submit_button("💾 Save New Story to Bank", type="primary", use_container_width=True)
            if submit_new_story:
                if not new_title.strip():
                    st.error("Please provide a story title.")
                else:
                    new_breadcrumbs = []
                    for lbl, knd, cnt in [(b1_label, b1_kind, b1_content), (b2_label, b2_kind, b2_content), (b3_label, b3_kind, b3_content), (b4_label, b4_kind, b4_content)]:
                        if lbl.strip() and cnt.strip():
                            new_breadcrumbs.append(StoryBreadcrumb(label=lbl.strip(), content=cnt.strip(), kind=knd))

                    if not new_breadcrumbs:
                        new_breadcrumbs = [StoryBreadcrumb(label="Milestone 1", content=new_title.strip(), kind="milestone")]

                    created_story = CanonicalStory(
                        story_id=f"story-{new_num}-{uuid.uuid4().hex[:4]}",
                        story_number=int(new_num),
                        title=new_title.strip(),
                        archetype_tags=[t.strip() for t in new_tags.split(",") if t.strip()] or ["General"],
                        competencies=[c.strip() for c in new_comps.split(",") if c.strip()],
                        industries=[i.strip() for i in new_inds.split(",") if i.strip()] or ["General"],
                        is_locked=bool(new_locked),
                        is_canonical=True,
                        hook=new_hook.strip(),
                        problem=new_problem.strip(),
                        turning_point=new_tp.strip(),
                        result=new_result.strip(),
                        learning=new_learning.strip(),
                        breadcrumbs=new_breadcrumbs,
                        trigger_keywords=[k.strip() for k in new_keywords.split(",") if k.strip()],
                        target_question_types=[q.strip() for q in new_questions.split("\n") if q.strip()],
                        transitions={}
                    )
                    StoryBankService.add_story(created_story)
                    st.session_state.story_bank = StoryBankService.load_stories()
                    st.success(f"🎉 Created Story {new_num}: '{new_title.strip()}' and saved to stories.json!")
                    st.rerun()

    # Filter stories
    filtered_stories = stories
    if story_search:
        ss = story_search.lower()
        filtered_stories = [
            s for s in filtered_stories
            if ss in s.title.lower()
            or ss in s.turning_point.lower()
            or ss in s.result.lower()
            or any(ss in c.lower() for c in s.competencies)
            or any(ss in kw.lower() for kw in s.trigger_keywords)
        ]
    if selected_tag != "All Themes":
        filtered_stories = [
            s for s in filtered_stories
            if any(selected_tag.lower() in t.lower() for t in s.archetype_tags)
        ]

    st.markdown(f"Showing **{len(filtered_stories)} of {len(stories)}** canonical stories:")

    # 3. Render Story Cards (Breadcrumbs as the Primary Visual)
    for s_idx, s in enumerate(filtered_stories):
        lock_icon = "🔒" if s.is_locked else "🔓"
        with st.expander(f"{lock_icon} **Story {s.story_number}: {s.title}** | *{', '.join(s.archetype_tags[:2])}*", expanded=False):
            # Top Action Bar: Badges + Lock Toggle
            col_hdr1, col_hdr2 = st.columns([3, 1])
            with col_hdr1:
                tags_html = ""
                for t in s.archetype_tags:
                    tags_html += f'<span class="badge-pill" style="background:#1E3A8A; color:#BFDBFE; font-weight:600;">{t}</span>'
                for comp in s.competencies:
                    tags_html += f'<span class="badge-pill" style="background:#064E3B; color:#A7F3D0; font-weight:600;">{comp}</span>'
                for ind in s.industries:
                    tags_html += f'<span class="badge-pill" style="background:#374151; color:#E5E7EB;">{ind}</span>'
                st.markdown(tags_html, unsafe_allow_html=True)
            with col_hdr2:
                btn_lock_label = "🔓 Unlock Story" if s.is_locked else "🔒 Lock Story"
                if st.button(btn_lock_label, key=f"btn_lock_{s.story_id}_{s_idx}"):
                    StoryBankService.toggle_story_lock(s.story_id)
                    st.session_state.story_bank = StoryBankService.load_stories()
                    st.rerun()

            # PRIMARY VISUAL: THE BREADCRUMB TRAIL STEPPER (FULL WIDTH)
            st.markdown("##### 🍞 Narrative Breadcrumbs (Quick Screen & Call Stepper):")
            render_breadcrumb_trail(s.breadcrumbs)

            # High-Impact Anchors: Turning Point & Result side-by-side
            c_anchor1, c_anchor2 = st.columns(2)
            with c_anchor1:
                st.markdown(f"""
                <div style="background:#1E293B; border-left:4px solid #6366F1; padding:10px 14px; border-radius:6px; min-height:85px; margin-bottom:12px;">
                    <div style="color:#A5B4FC; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">⚡ The Turning Point</div>
                    <div style="color:#F8FAFC; font-size:0.92rem; font-weight:500; margin-top:4px;">{s.turning_point}</div>
                </div>
                """, unsafe_allow_html=True)
            with c_anchor2:
                st.markdown(f"""
                <div style="background:#064E3B; border-left:4px solid #10B981; padding:10px 14px; border-radius:6px; min-height:85px; margin-bottom:12px;">
                    <div style="color:#6EE7B7; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">📊 Proven Result & Metrics</div>
                    <div style="color:#ECFDF5; font-size:0.92rem; font-weight:600; margin-top:4px;">{s.result}</div>
                </div>
                """, unsafe_allow_html=True)

            # Sub-Section 1: Full Narrative & Context
            with st.expander("🔍 View Full Narrative, Hook & Transition Details", expanded=False):
                col_n1, col_n2 = st.columns(2)
                with col_n1:
                    st.markdown(f"**Elevator Hook:**\n*{s.hook}*")
                    st.markdown(f"**The Problem & Stakes:**\n{s.problem}")
                    st.markdown(f"**💡 Lasting Philosophy & Takeaway:**\n{s.learning}")
                with col_n2:
                    if s.transitions:
                        st.markdown("**🌉 Interview Narrative Bridges (Transitions):**")
                        for target_sid, trans_text in s.transitions.items():
                            target_num = target_sid.replace("story-", "")
                            st.caption(f"➔ **To Story {target_num}:** *\"{trans_text}\"*")
                    st.markdown("**🎯 Question Types This Story Answers:**")
                    for q_ans in s.target_question_types:
                        st.write(f"• {q_ans}")
                    if s.trigger_keywords:
                        st.caption(f"**Trigger Keywords:** {', '.join(s.trigger_keywords)}")

            # Sub-Section 2: Full In-App Story & Breadcrumb Editor
            with st.expander(f"✏️ Edit Story {s.story_number} Information, Tags & Breadcrumbs", expanded=False):
                with st.form(key=f"edit_story_form_{s.story_id}_{s_idx}"):
                    st.markdown(f"#### ✏️ Full Editor: Story {s.story_number}")
                    if s.is_locked:
                        st.caption("ℹ️ *This story is locked to prevent automated background updates, but your manual edits here will be saved directly.*")

                    c_e1, c_e2 = st.columns([2, 1])
                    with c_e1:
                        ed_title = st.text_input("Story Title", value=s.title, key=f"ed_t_{s.story_id}_{s_idx}")
                    with c_e2:
                        ed_arch = st.text_input("Archetype Tags (comma-separated)", value=", ".join(s.archetype_tags), key=f"ed_arch_{s.story_id}_{s_idx}")

                    c_e3, c_e4 = st.columns([1, 1])
                    with c_e3:
                        ed_comps = st.text_input("Competencies / Tech Stack (comma-separated)", value=", ".join(s.competencies), key=f"ed_comp_{s.story_id}_{s_idx}")
                    with c_e4:
                        ed_inds = st.text_input("Target Industries (comma-separated)", value=", ".join(s.industries), key=f"ed_ind_{s.story_id}_{s_idx}")

                    ed_hook = st.text_area("Elevator Hook (1-2 sentences)", value=s.hook, height=70, key=f"ed_hk_{s.story_id}_{s_idx}")
                    ed_problem = st.text_area("The Problem & High Stakes", value=s.problem, height=85, key=f"ed_prob_{s.story_id}_{s_idx}")

                    c_e5, c_e6 = st.columns(2)
                    with c_e5:
                        ed_tp = st.text_area("⚡ The Turning Point", value=s.turning_point, height=85, key=f"ed_tp_{s.story_id}_{s_idx}")
                    with c_e6:
                        ed_result = st.text_area("📊 Measurable Result & Metrics", value=s.result, height=85, key=f"ed_res_{s.story_id}_{s_idx}")

                    ed_learning = st.text_area("💡 Lasting Learning & Philosophy", value=s.learning, height=75, key=f"ed_learn_{s.story_id}_{s_idx}")

                    st.markdown("---")
                    st.markdown("##### 🍞 Edit Existing Breadcrumb Milestones:")
                    ed_breadcrumbs = []
                    kind_options = ["context", "pivot", "milestone", "metric", "learning"]
                    for b_i, b_item in enumerate(s.breadcrumbs):
                        b_c1, b_c2, b_c3, b_c4 = st.columns([2, 5, 2, 1])
                        with b_c1:
                            b_lbl = st.text_input(f"Step {b_i+1} Label", value=b_item.label, key=f"ed_bl_{s.story_id}_{b_i}_{s_idx}")
                        with b_c2:
                            b_cnt = st.text_input(f"Step {b_i+1} Soundbite", value=b_item.content, key=f"ed_bc_{s.story_id}_{b_i}_{s_idx}")
                        with b_c3:
                            b_k_idx = kind_options.index(b_item.kind) if b_item.kind in kind_options else 0
                            b_knd = st.selectbox(f"Kind", kind_options, index=b_k_idx, key=f"ed_bk_{s.story_id}_{b_i}_{s_idx}")
                        with b_c4:
                            st.write("")
                            b_remove = st.checkbox("Delete", key=f"del_b_{s.story_id}_{b_i}_{s_idx}", help="Remove this breadcrumb")

                        if not b_remove:
                            ed_breadcrumbs.append(StoryBreadcrumb(id=b_item.id, label=b_lbl, content=b_cnt, kind=b_knd))

                    st.markdown("##### ➕ Add An Extra Milestone (Optional):")
                    extra_c1, extra_c2, extra_c3 = st.columns([2, 5, 2])
                    with extra_c1:
                        ex_lbl = st.text_input("New Label", placeholder="e.g. Outcome", key=f"ex_lbl_{s.story_id}_{s_idx}")
                    with extra_c2:
                        ex_cnt = st.text_input("New Soundbite", placeholder="e.g. Reconciled $410K gap", key=f"ex_cnt_{s.story_id}_{s_idx}")
                    with extra_c3:
                        ex_knd = st.selectbox("Kind", kind_options, index=2, key=f"ex_knd_{s.story_id}_{s_idx}")

                    st.markdown("---")
                    c_e7, c_e8 = st.columns([1, 1])
                    with c_e7:
                        ed_keywords = st.text_input("Trigger Keywords (comma-separated)", value=", ".join(s.trigger_keywords), key=f"ed_kw_{s.story_id}_{s_idx}")
                    with c_e8:
                        ed_questions = st.text_area("Target Question Types (one per line)", value="\n".join(s.target_question_types), height=90, key=f"ed_q_{s.story_id}_{s_idx}")

                    c_b1, c_b2 = st.columns([3, 1])
                    with c_b1:
                        btn_save_story = st.form_submit_button("💾 Save All Story Changes & Update Knowledge Base", type="primary", use_container_width=True)
                    with c_b2:
                        btn_del_story = st.form_submit_button("🗑️ Delete Story", use_container_width=True)

                    if btn_del_story:
                        StoryBankService.delete_story(s.story_id)
                        st.session_state.story_bank = StoryBankService.load_stories()
                        st.success(f"Deleted Story {s.story_number} from stories.json!")
                        st.rerun()

                    if btn_save_story:
                        if not ed_title.strip():
                            st.error("Story title cannot be empty.")
                        else:
                            final_breadcrumbs = [b for b in ed_breadcrumbs if b.label.strip() and b.content.strip()]
                            if ex_lbl.strip() and ex_cnt.strip():
                                final_breadcrumbs.append(StoryBreadcrumb(label=ex_lbl.strip(), content=ex_cnt.strip(), kind=ex_knd))

                            updated_dict = {
                                "title": ed_title.strip(),
                                "archetype_tags": [t.strip() for t in ed_arch.split(",") if t.strip()],
                                "competencies": [c.strip() for c in ed_comps.split(",") if c.strip()],
                                "industries": [i.strip() for i in ed_inds.split(",") if i.strip()],
                                "hook": ed_hook.strip(),
                                "problem": ed_problem.strip(),
                                "turning_point": ed_tp.strip(),
                                "result": ed_result.strip(),
                                "learning": ed_learning.strip(),
                                "breadcrumbs": [b.model_dump() for b in final_breadcrumbs],
                                "trigger_keywords": [k.strip() for k in ed_keywords.split(",") if k.strip()],
                                "target_question_types": [q.strip() for q in ed_questions.split("\n") if q.strip()]
                            }
                            StoryBankService.update_story(s.story_id, updated_dict, is_user_override=True)
                            st.session_state.story_bank = StoryBankService.load_stories()
                            st.success(f"Saved changes to Story {s.story_number} ('{ed_title.strip()}')!")
                            st.rerun()


# =====================================================================
# TAB 4: INTEGRATIONS & EXPANSION (PLACEHOLDERS & ROADMAP)
# =====================================================================
with tab4:
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

