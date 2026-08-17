import sys
import os
import argparse
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

from job_pipeline.domain.models import CandidateProfile, JobPosting
from job_pipeline.domain.services import JobQualificationService
from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter
from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter
from job_pipeline.adapters.secondary.openai_adapter import OpenAIEngineAdapter
from job_pipeline.adapters.secondary.mock_adapter import (
    MockJobStorageAdapter,
    MockDocumentStorageAdapter,
    MockResumeRepositoryAdapter,
    MockLLMStrategyAdapter
)


def evaluate_single_job(
    company_name: str,
    job_title: str,
    title_family: str,
    raw_jd: str,
    salary_min: Optional[float] = None,
    salary_max: Optional[float] = None,
    demo_mode: bool = False
):
    profile = CandidateProfile()

    if demo_mode:
        print("INFO: Running Single Job Evaluation in DEMO MODE...")
        storage_adapter = MockJobStorageAdapter()
        drive_adapter = MockDocumentStorageAdapter()
        resume_repo = MockResumeRepositoryAdapter()
        llm_adapter = MockLLMStrategyAdapter()
        telemetry = None
    else:
        print(f"RUNNING: Evaluating Job Posting '{company_name} - {job_title}' via LLM Telemetry Extractor...")
        storage_adapter = GoogleSheetsAdapter()
        drive_adapter = GoogleDriveAdapter()
        resume_repo = drive_adapter
        llm_adapter = OpenAIEngineAdapter()
        
        # 0. Extract Telemetry via OpenAI gpt-4o-mini
        try:
            telemetry = llm_adapter.extract_job_telemetry(raw_jd)
            if company_name in ["Planful", "Stripe Analytics", "Target Company"] and telemetry.company_name:
                company_name = telemetry.company_name
            if job_title in ["Sales Operations Analyst", "Senior Revenue Operations Analyst", "Target Role"] and telemetry.job_title:
                job_title = telemetry.job_title
            if telemetry.title_family:
                title_family = telemetry.title_family
            if salary_min is None or salary_min == 0:
                salary_min = telemetry.requirements.salary_min
            if salary_max is None or salary_max == 0:
                salary_max = telemetry.requirements.salary_max
        except Exception as e:
            print(f"WARNING: Telemetry extraction fallback: {e}")
            telemetry = None

    req_skills = telemetry.requirements.required_tech_stack if telemetry else []
    pref_skills = telemetry.requirements.preferred_tech_stack if telemetry else []

    # 1. Run Qualification & Pay Calculator
    fit_eval = JobQualificationService.evaluate(
        company_name=company_name,
        job_title=job_title,
        raw_description=raw_jd,
        required_skills=req_skills,
        preferred_skills=pref_skills,
        salary_min=salary_min,
        salary_max=salary_max,
        profile=profile
    )
    print("\n--- FIT QUALIFICATION RESULT ---")
    print(f"Status:      {fit_eval.status}")
    print(f"Reasoning:   {fit_eval.reasoning}")
    print(f"Target Pay:  {fit_eval.pay_bounds.display_range}")
    if req_skills:
        print(f"Required Tech: {', '.join(req_skills)}")
    if pref_skills:
        print(f"Preferred Tech: {', '.join(pref_skills)}")

    # 2. Select Best Fit Resume
    selected_resume = resume_repo.select_best_fit_resume(job_title, title_family)
    resume_name = selected_resume.filename if selected_resume else "Default Resume"
    print(f"Matched Resume: {resume_name}")

    resume_text = resume_repo.fetch_resume_text(selected_resume.doc_id) if selected_resume else ""

    # 3. Create Application Workspace in Drive
    workspace = drive_adapter.create_application_workspace(company_name, job_title)
    folder_id = workspace.get("folder_id")
    folder_link = workspace.get("folder_link")
    print(f"Drive Workspace Folder: {folder_link}")

    # 4. Generate Role Intelligence Report
    docx_filename = f"{company_name.replace(' ', '_')}_Role_Intelligence_Report.docx"
    output_docx_path = f"output_reports/{docx_filename}"

    report = llm_adapter.generate_role_intelligence_report(
        job_data={"company": company_name, "title": job_title, "description": raw_jd},
        resume_data={"resume_id": selected_resume.doc_id if selected_resume else "res-1", "text": resume_text},
        output_docx_path=output_docx_path,
        target_pay_bounds=fit_eval.pay_bounds.model_dump(),
        demo_mode=demo_mode
    )
    # Save local raw JD backup file
    raw_jd_path = f"output_reports/{company_name.replace(' ', '_')}_Raw_JD.txt"
    try:
        with open(raw_jd_path, "w", encoding="utf-8") as f_jd:
            f_jd.write(raw_jd)
    except Exception:
        pass

    # 5. Upload Assets to Google Drive Workspace Folder
    drive_jd_link = None
    if folder_id:
        print("UPLOADING assets to Google Drive folder...")
        jd_file_res = drive_adapter.upload_raw_job_description(folder_id, raw_jd)
        if isinstance(jd_file_res, dict):
            drive_jd_link = jd_file_res.get("file_link")
        if selected_resume and selected_resume.doc_id:
            drive_adapter.export_resume_pdf(selected_resume.doc_id, folder_id, f"{resume_name}.pdf")
        if os.path.exists(output_docx_path):
            drive_adapter.upload_role_intelligence_report(folder_id, output_docx_path)

    # 6. Save Opportunity Record & Requirements to Google Sheets
    import uuid
    tot_tokens = getattr(llm_adapter, "last_telemetry_tokens", 0) + getattr(llm_adapter, "last_report_tokens", 0)
    job_item = JobPosting(
        opportunity_id=str(uuid.uuid4()),
        company_name=company_name,
        job_title=job_title,
        title_family=title_family,
        raw_description=raw_jd,
        required_skills=req_skills,
        preferred_skills=pref_skills,
        selected_resume_name=resume_name,
        drive_folder_link=folder_link,
        drive_jd_link=drive_jd_link,
        tokens_used=tot_tokens
    )
    storage_adapter.save_opportunity(job_item, fit_eval)

    print("\nSUCCESS: Single Job Evaluation Completed & Saved to Google Sheets!")
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate a single job posting via CLI")
    parser.add_argument("--company", default="Stripe Analytics", help="Company Name")
    parser.add_argument("--title", default="Senior Revenue Operations Analyst", help="Job Title")
    parser.add_argument("--family", default="revenue_operations", help="Role Family")
    parser.add_argument("--jd", help="Path to text file containing Job Description")
    parser.add_argument("--min-pay", type=float, default=120000, help="Posted min salary")
    parser.add_argument("--max-pay", type=float, default=170000, help="Posted max salary")
    parser.add_argument("--demo", action="store_true", help="Run in zero-cost demo mode")
    args = parser.parse_args()

    if args.jd and os.path.exists(args.jd):
        with open(args.jd, "r", encoding="utf-8") as f:
            raw_jd = f.read()
    else:
        raw_jd = (
            "Seeking a Senior RevOps Analyst to own Salesforce architecture, build dbt models in BigQuery, "
            "manage HubSpot lead routing, and align GTM conversion metrics across Sales, Marketing, and Finance. "
            "Required skills: Salesforce, SQL, dbt, HubSpot, RevOps."
        )

    evaluate_single_job(
        company_name=args.company,
        job_title=args.title,
        title_family=args.family,
        raw_jd=raw_jd,
        salary_min=args.min_pay,
        salary_max=args.max_pay,
        demo_mode=args.demo
    )


if __name__ == "__main__":
    main()
