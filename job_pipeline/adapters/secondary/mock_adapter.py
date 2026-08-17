import os
import uuid
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting, FitEvaluation, RoleIntelligenceReport
from job_pipeline.ports.storage_port import JobStoragePort, DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.ports.llm_port import LLMStrategyPort


class MockJobStorageAdapter(JobStoragePort):
    def __init__(self):
        self.saved_jobs: List[Dict[str, Any]] = []

    def fetch_pending_jobs(self) -> List[JobPosting]:
        return [
            JobPosting(
                opportunity_id="opp_mock_1",
                company_name="Mock RevOps Corp",
                job_title="Revenue Operations Analyst",
                title_family="revenue_operations",
                raw_description="Seeking a RevOps Analyst to own Salesforce and HubSpot lead routing, build dbt models, and align GTM SLAs across Sales, Marketing, and Finance. Required stack: Salesforce, SQL, dbt, HubSpot.",
                source_url="https://example.com/jobs/revops-analyst"
            )
        ]

    def save_opportunity(self, job: JobPosting, fit_eval: FitEvaluation) -> bool:
        self.saved_jobs.append({"job": job, "fit_eval": fit_eval})
        print(f"MOCK STORAGE: Saved job '{job.company_name} - {job.job_title}'")
        return True

    def update_opportunity_status(self, opportunity_id: str, status: str, notes: Optional[str] = None) -> bool:
        return True


class MockDocumentStorageAdapter(DocumentStoragePort):
    def create_application_workspace(self, company_name: str, job_title: str) -> Dict[str, str]:
        return {"folder_id": "mock_drive_folder_id", "folder_link": "https://drive.google.com/mock_folder"}

    def upload_raw_job_description(self, folder_id: str, raw_text: str) -> Optional[str]:
        return "mock_raw_jd_file_id"

    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        return "mock_pdf_resume_id"

    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        return "mock_docx_report_id"


class MockResumeRepositoryAdapter(ResumeRepositoryPort):
    def list_available_resumes(self) -> List[ResumeFileRef]:
        return [
            ResumeFileRef(doc_id="doc_mock_revops", filename="Candidate RevOps Analyst Resume", role_label="Revenue Operations"),
            ResumeFileRef(doc_id="doc_mock_gtm", filename="Candidate GTM Engineer Resume", role_label="GTM Engineering"),
            ResumeFileRef(doc_id="doc_mock_ba", filename="Candidate Business Analyst Resume", role_label="Business Analytics")
        ]

    def fetch_resume_text(self, doc_id: str) -> str:
        return "Built dbt models, SQL funnel analytics, Salesforce RevOps automation, and BigQuery telemetry pipelines."

    def select_best_fit_resume(self, job_title: str, title_family: str) -> Optional[ResumeFileRef]:
        resumes = self.list_available_resumes()
        for r in resumes:
            if "revops" in r.filename.lower() or "operations" in r.filename.lower():
                return r
        return resumes[0]


class MockLLMStrategyAdapter(LLMStrategyPort):
    def generate_role_intelligence_report(
        self,
        job_data: Dict[str, Any],
        resume_data: Dict[str, Any],
        output_docx_path: str,
        target_pay_bounds: Optional[Dict[str, Any]] = None,
        demo_mode: bool = False
    ) -> RoleIntelligenceReport:
        os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
        # Create a dummy docx file if it doesn't exist
        with open(output_docx_path, "wb") as f:
            f.write(b"MOCK_ROLE_INTELLIGENCE_REPORT_DOCX_BYTES")

        return RoleIntelligenceReport(
            document_title=f"Role Intelligence Report - {job_data.get('company', 'Mock Company')}",
            company=job_data.get("company", "Mock Company"),
            job_title=job_data.get("title", "Mock Title"),
            output_docx_path=output_docx_path
        )
