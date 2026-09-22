import os
import sys
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


def run_batch_pipeline(demo_mode: bool = False):
    """Primary Driving Adapter: Runs batch ingestion from Google Sheets or Mock Data."""

    profile = CandidateProfile()

    if demo_mode:
        print("INFO: Running Batch Pipeline in MOCK / DEMO MODE...")
        storage_adapter = MockJobStorageAdapter()
        drive_adapter = MockDocumentStorageAdapter()
        resume_repo = MockResumeRepositoryAdapter()
        llm_adapter = MockLLMStrategyAdapter()
    else:
        print("RUNNING: Connecting to Live Infrastructure Adapters...")
        storage_adapter = GoogleSheetsAdapter()
        drive_adapter = GoogleDriveAdapter()
        resume_repo = drive_adapter
        llm_adapter = OpenAIEngineAdapter()

    pending_jobs = storage_adapter.fetch_pending_jobs()
    print(f"TOTAL PENDING JOBS FOUND: {len(pending_jobs)}")

    for job in pending_jobs:
        # 0. Extract Telemetry via OpenAI gpt-4o-mini if raw JD text is present
        sal_min, sal_max = None, None
        if not demo_mode and isinstance(llm_adapter, OpenAIEngineAdapter) and len(job.raw_description) >= 20:
            try:
                print(f"\nEXTRACTING LLM Telemetry from raw JD text...")
                telemetry = llm_adapter.extract_job_telemetry(job.raw_description)
                if telemetry.company_name and (not job.company_name or len(job.company_name.strip()) < 2):
                    job.company_name = telemetry.company_name
                if telemetry.job_title and (not job.job_title or len(job.job_title.strip()) < 2):
                    job.job_title = telemetry.job_title
                if telemetry.title_family:
                    job.title_family = telemetry.title_family

                job.required_skills = telemetry.requirements.required_tech_stack
                job.preferred_skills = telemetry.requirements.preferred_tech_stack
                sal_min = telemetry.requirements.salary_min
                sal_max = telemetry.requirements.salary_max
            except Exception as e:
                print(f"WARNING: Telemetry extraction notice: {e}")

        print(f"\nPROCESSING JOB: {job.company_name} - {job.job_title} ({job.title_family})")

        # Fetch existing opportunities for duplicate & velocity guardrails
        all_opps = storage_adapter.fetch_all_opportunities()

        # 1. Run Qualification & Target Pay Calculator (60%-80%)
        fit_eval = JobQualificationService.evaluate(
            company_name=job.company_name,
            job_title=job.job_title,
            raw_description=job.raw_description,
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            salary_min=sal_min,
            salary_max=sal_max,
            profile=profile,
            existing_company_titles=all_opps
        )
        print(f"  FIT GUARDRAIL RESULT: {fit_eval.status} - {fit_eval.reasoning}")
        print(f"  TARGET PAY RANGE:     {fit_eval.pay_bounds.display_range}")

        # 2. Select Best-Fit Resume by Title
        selected_resume = resume_repo.select_best_fit_resume(job.job_title, job.title_family)
        resume_name = selected_resume.filename if selected_resume else "Default Resume"
        job.selected_resume_name = resume_name
        print(f"  SELECTED RESUME: {resume_name}")

        resume_text = resume_repo.fetch_resume_text(selected_resume.doc_id) if selected_resume else ""

        # 3. Create Google Drive Application Workspace
        workspace = drive_adapter.create_application_workspace(job.company_name, job.job_title)
        job.drive_folder_link = workspace.get("folder_link")

        # 4. Generate Role Intelligence Report DOCX
        docx_filename = f"{job.company_name.replace(' ', '_')}_Role_Intelligence_Report.docx"
        output_docx_path = f"output_reports/{docx_filename}"

        report = llm_adapter.generate_role_intelligence_report(
            job_data={"company": job.company_name, "title": job.job_title, "description": job.raw_description},
            resume_data={"resume_id": selected_resume.doc_id if selected_resume else "res-1", "text": resume_text},
            output_docx_path=output_docx_path,
            target_pay_bounds=fit_eval.pay_bounds.model_dump(),
            demo_mode=demo_mode
        )

        job.tokens_used = getattr(llm_adapter, "last_telemetry_tokens", 0) + getattr(llm_adapter, "last_report_tokens", 0)

        # 5. Upload Assets to Drive Workspace (Raw JD Document + PDF Resume + DOCX Report)
        if workspace.get("folder_id"):
            jd_file_res = drive_adapter.upload_raw_job_description(
                workspace["folder_id"],
                job.raw_description,
                company_name=job.company_name,
                job_title=job.job_title
            )
            if isinstance(jd_file_res, dict):
                job.drive_jd_link = jd_file_res.get("file_link")
            if selected_resume and selected_resume.doc_id:
                drive_adapter.export_resume_pdf(selected_resume.doc_id, workspace["folder_id"], f"{resume_name}.pdf")
            drive_adapter.upload_role_intelligence_report(workspace["folder_id"], output_docx_path)

        # 6. Save Opportunity to Google Sheets
        storage_adapter.save_opportunity(job, fit_eval)

    print("\nSUCCESS: Batch Pipeline Execution Completed!")


if __name__ == "__main__":
    is_demo = "--demo" in sys.argv or os.environ.get("DEMO_MODE", "false").lower() == "true"
    run_batch_pipeline(demo_mode=is_demo)
