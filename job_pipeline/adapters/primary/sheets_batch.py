import os
import sys
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

from job_pipeline.domain.models import CandidateProfile, JobPosting
from job_pipeline.domain.services import JobQualificationService, PipelineConfigService
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
        # 0. Extract Telemetry via OpenAI gpt-6-luna if raw JD text is present
        sal_min, sal_max = None, None
        warning_rules = PipelineConfigService.get_active_warning_rules()
        telemetry_warnings = []
        telemetry_flags = []
        telemetry_benefits = []
        if len(job.raw_description) >= 20:
            try:
                print(f"\nEXTRACTING Job Signals from raw JD text...")
                telemetry = llm_adapter.extract_job_telemetry(job.raw_description, warning_rules=warning_rules)
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
                telemetry_warnings = telemetry.requirements.telemetry_warnings or []
                telemetry_flags = telemetry.requirements.telemetry_flags or []
                telemetry_benefits = telemetry.requirements.telemetry_benefits or []
            except Exception as e:
                print(f"WARNING: Job Signals extraction notice: {e}")

        job.telemetry_warnings = telemetry_warnings
        job.telemetry_flags = telemetry_flags
        job.telemetry_benefits = telemetry_benefits
        print(f"\nPROCESSING JOB: {job.company_name} - {job.job_title} ({job.title_family})")

        # Fetch existing opportunities for duplicate & velocity guardrails
        all_opps = storage_adapter.fetch_all_opportunities()

        # 1. Run Qualification & Target Pay Calculator
        fit_eval = JobQualificationService.evaluate(
            company_name=job.company_name,
            job_title=job.job_title,
            raw_description=job.raw_description,
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            salary_min=sal_min,
            salary_max=sal_max,
            profile=profile,
            existing_company_titles=all_opps,
            telemetry_warnings=telemetry_warnings,
            telemetry_flags=telemetry_flags,
            telemetry_benefits=telemetry_benefits,
        )
        print(f"  FIT GUARDRAIL RESULT: {fit_eval.status} - {fit_eval.reasoning}")
        print(f"  TARGET PAY RANGE:     {fit_eval.pay_bounds.display_range}")
        for label, findings in (("Flags", telemetry_flags), ("Warnings", telemetry_warnings), ("Positive Signals", telemetry_benefits)):
            if findings:
                print(f"  Job Signals — {label}:")
                for finding in findings:
                    print(f"    {finding}")

        # 2. Select Best-Fit Resume by Title
        selected_resume = resume_repo.select_best_fit_resume(job.job_title, job.title_family)
        resume_name = selected_resume.filename if selected_resume else "Default Resume"
        job.selected_resume_name = resume_name
        print(f"  SELECTED RESUME: {resume_name}")

        # 3. Create Google Drive Application Workspace
        workspace = drive_adapter.create_application_workspace(job.company_name, job.job_title)
        job.drive_folder_link = workspace.get("folder_link")

        job.tokens_used = getattr(llm_adapter, "last_telemetry_tokens", 0)
        job.role_intelligence_status = "Not Generated"

        # 4. Upload Assets to Drive Workspace (Raw JD Document + PDF Resume)
        if workspace.get("folder_id"):
            jd_file_res = drive_adapter.upload_raw_job_description(
                workspace["folder_id"],
                job.raw_description,
                company_name=job.company_name,
                job_title=job.job_title
            )
            if isinstance(jd_file_res, dict):
                job.drive_jd_link = jd_file_res.get("file_link") or jd_file_res.get("webViewLink")
            if selected_resume and selected_resume.doc_id:
                drive_adapter.export_resume_pdf(selected_resume.doc_id, workspace["folder_id"], f"{resume_name}.pdf")

        try:
            raw_jd_dir = Path("output_reports") / uuid.uuid5(uuid.NAMESPACE_URL, job.opportunity_id).hex
            raw_jd_dir.mkdir(parents=True, exist_ok=True)
            (raw_jd_dir / "Raw_JD.txt").write_text(job.raw_description or "", encoding="utf-8")
        except Exception:
            pass

        # 5. Save Opportunity to Google Sheets
        storage_adapter.save_opportunity(job, fit_eval)

    print("\nSUCCESS: Job ingestion complete. Role Intelligence deferred until employer interest or manual generation.")


if __name__ == "__main__":
    is_demo = "--demo" in sys.argv or os.environ.get("DEMO_MODE", "false").lower() == "true"
    run_batch_pipeline(demo_mode=is_demo)
