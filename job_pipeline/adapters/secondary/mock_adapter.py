import os
import uuid
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting, FitEvaluation, RoleIntelligenceReport, ScreeningQA
from job_pipeline.ports.storage_port import JobStoragePort, DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.ports.llm_port import LLMStrategyPort


class MockJobStorageAdapter(JobStoragePort):
    def __init__(self):
        self.saved_jobs: List[Dict[str, Any]] = []
        self.screening_qa_store: List[Dict[str, Any]] = []

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

    def update_opportunity_status(
        self,
        opportunity_id: str,
        status: str,
        notes: Optional[str] = None,
        stage_history: Optional[List[Dict[str, str]]] = None,
        category: Optional[str] = None,
        applied_via: Optional[str] = None,
        priority: Optional[str] = None,
        employment_arrangement: Optional[str] = None,
        worker_classification: Optional[str] = None,
        pay_basis: Optional[str] = None,
        contract_length_raw: Optional[str] = None,
        contract_value_display: Optional[str] = None,
        staffing_agency: Optional[str] = None,
        client_company: Optional[str] = None,
        extension_possible: Optional[bool] = None,
        fte_conversion_possible: Optional[bool] = None
    ) -> bool:
        for item in self.saved_jobs:
            j = item["job"]
            if j.opportunity_id == opportunity_id:
                j.status = status
                if stage_history is not None:
                    j.stage_history = stage_history
                if category is not None:
                    j.category = category
                if applied_via is not None:
                    j.applied_via = applied_via
                if priority is not None:
                    j.priority = priority
                if employment_arrangement is not None:
                    j.employment_arrangement = employment_arrangement
                if worker_classification is not None:
                    j.worker_classification = worker_classification
                if pay_basis is not None:
                    j.pay_basis = pay_basis
                if contract_length_raw is not None:
                    j.contract_length_raw = contract_length_raw
                if contract_value_display is not None:
                    j.contract_value_display = contract_value_display
                if staffing_agency is not None:
                    j.staffing_agency = staffing_agency
                if client_company is not None:
                    j.client_company = client_company
                if extension_possible is not None:
                    j.extension_possible = extension_possible
                if fte_conversion_possible is not None:
                    j.fte_conversion_possible = fte_conversion_possible
                item["notes"] = notes
                return True
        return True

    def fetch_all_opportunities(self) -> List[Dict[str, Any]]:
        results = []
        for item in self.saved_jobs:
            j = item["job"]
            fe = item["fit_eval"]
            sh = j.stage_history or [{"stage": j.status, "entered_at": "2026-09-22T08:14:00"}]
            results.append({
                "Company Name": j.company_name,
                "Job Title": j.job_title,
                "Date Created": j.date_created,
                "Status": j.status,
                "Category": j.category or "Target",
                "Applied Via": j.applied_via or "LinkedIn",
                "Priority": j.priority or "High",
                "Employment Arrangement": j.employment_arrangement or "Employee",
                "Worker Classification": j.worker_classification or "",
                "Pay Basis": j.pay_basis or "Annual",
                "Contract Duration": j.contract_length_raw or "",
                "Contract Value": j.contract_value_display or (fe.pay_bounds.contract_value_display or ""),
                "Staffing Agency": j.staffing_agency or "",
                "Client Company": j.client_company or "",
                "Extension Possible": "Yes" if j.extension_possible is True else ("No" if j.extension_possible is False else ""),
                "FTE Conversion": "Yes" if j.fte_conversion_possible is True else ("No" if j.fte_conversion_possible is False else ""),
                "Stage History": sh,
                "stage_history": sh,
                "Notes": item.get("notes", ""),
                "Opportunity ID": j.opportunity_id,
                "Target Pay Range": fe.pay_bounds.display_range,
                "Fit Warning": fe.reasoning,
                "Drive Folder Link": j.drive_folder_link or "https://drive.google.com/mock_folder"
            })
        return results

    def save_screening_qa(
        self,
        opportunity_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        gdoc_link: Optional[str] = None
    ) -> bool:
        for q in qa_items:
            self.screening_qa_store.append({
                "opportunity_id": opportunity_id,
                "company_name": company_name,
                "job_title": job_title,
                "question": q.question,
                "answer": q.answer,
                "category": q.category,
                "timestamp": q.created_at,
                "gdoc_link": gdoc_link or "https://docs.google.com/document/d/mock_screening_qa/edit"
            })
        return True

    def fetch_screening_qa(self, opportunity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if opportunity_id:
            return [q for q in self.screening_qa_store if q.get("opportunity_id") == opportunity_id]
        return self.screening_qa_store

    def append_call_note(self, opportunity_id: str, note_text: str, call_type: str = "Call", interviewer: str = "") -> bool:
        for opp in self.saved_jobs:
            if opp.get("Opportunity ID") == opportunity_id:
                prev_notes = opp.get("Notes", "")
                who = f" (with {interviewer.strip()})" if interviewer else ""
                entry = f"[{call_type}{who}]: {note_text}"
                opp["Notes"] = f"{prev_notes}\n{entry}" if prev_notes else entry
                return True
        return True

    def update_opportunity_screening_doc(self, opportunity_id: str, gdoc_link: str, qa_count: int) -> bool:
        for opp in self.saved_jobs:
            if opp.get("Opportunity ID") == opportunity_id:
                opp["Screening Doc Link"] = gdoc_link
                opp["Screening QA Count"] = qa_count
                return True
        return True


class MockDocumentStorageAdapter(DocumentStoragePort):
    def create_application_workspace(self, company_name: str, job_title: str) -> Dict[str, str]:
        return {"folder_id": "mock_drive_folder_id", "folder_link": "https://drive.google.com/mock_folder"}

    def upload_raw_job_description(self, folder_id: str, raw_text: str, company_name: str = "", job_title: str = "") -> Optional[Dict[str, str]]:
        return {"file_id": "mock_raw_jd_file_id", "file_link": "https://docs.google.com/document/d/mock_raw_jd/edit"}

    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        return "mock_pdf_resume_id"

    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        return "mock_docx_report_id"

    def create_screening_questions_doc(
        self,
        folder_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        opportunity_id: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        return {"file_id": "mock_screening_doc_id", "file_link": "https://docs.google.com/document/d/mock_screening_questions/edit"}


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


import re
from job_pipeline.adapters.secondary.openai_adapter import JobExtractionPayload, JobRequirementsSchema


class MockLLMStrategyAdapter(LLMStrategyPort):
    def extract_job_telemetry(
        self,
        raw_jd: str,
        warning_rules: Optional[List[Dict[str, Any]]] = None
    ) -> JobExtractionPayload:
        if warning_rules is None:
            try:
                from job_pipeline.domain.services import PipelineConfigService
                warning_rules = PipelineConfigService.get_active_warning_rules()
            except Exception:
                warning_rules = []

        detected_warnings: List[str] = []
        if warning_rules:
            for rule in warning_rules:
                r_name = rule.get("name", "Warning")
                keywords = rule.get("keywords", [])
                matched_kws = []
                for kw in keywords:
                    if kw and kw.strip():
                        pattern = r'(?:\b|_)' + re.escape(kw.strip()) + r'(?:\b|_)'
                        if re.search(pattern, raw_jd, re.IGNORECASE):
                            matched_kws.append(kw.strip())
                if matched_kws:
                    kws_str = ", ".join(f"'{k}'" for k in set(matched_kws))
                    detected_warnings.append(f"[{r_name}]: Keyword match detected ({kws_str}).")

        return JobExtractionPayload(
            company_name="Mock Target Company",
            job_title="Revenue Operations Analyst",
            title_family="revenue_operations",
            requirements=JobRequirementsSchema(
                required_tech_stack=["Salesforce", "SQL", "Tableau", "dbt"],
                preferred_tech_stack=["HubSpot", "Clari"],
                core_pain_points="Pipeline acceleration and telemetry orchestration.",
                is_remote=True,
                employment_arrangement="Employee",
                pay_basis="Annual",
                telemetry_warnings=detected_warnings
            )
        )

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

