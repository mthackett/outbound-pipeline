from job_pipeline.domain.telemetry_service import TelemetryService
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from job_pipeline.domain.models import JobPosting, FitEvaluation, RoleIntelligenceReport, ScreeningQA
from job_pipeline.ports.storage_port import JobStoragePort, DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.ports.llm_port import LLMStrategyPort


class MockJobStorageAdapter(JobStoragePort):
    def __init__(self):
        self.is_connected = True
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
        raw_jd_link = job.drive_jd_link
        existing = next((item for item in self.saved_jobs if item["job"].opportunity_id == job.opportunity_id), None)
        if existing:
            if not raw_jd_link and existing.get("job") and existing["job"].drive_jd_link:
                raw_jd_link = existing["job"].drive_jd_link
                job.drive_jd_link = raw_jd_link
            existing.update(job=job, fit_eval=fit_eval)
        else:
            self.saved_jobs.append({"job": job, "fit_eval": fit_eval})
        if job.screening_qa:
            self.save_screening_qa(job.opportunity_id, job.company_name, job.job_title, job.screening_qa, job.drive_screening_doc_link)
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
        fte_conversion_possible: Optional[bool] = None,
        company_name: Optional[str] = None,
        job_title: Optional[str] = None,
        target_pay_range: Optional[str] = None,
        source_url: Optional[str] = None
    ) -> bool:
        for item in self.saved_jobs:
            j = item["job"]
            if j.opportunity_id == opportunity_id:
                j.status = status
                if company_name is not None:
                    j.company_name = company_name
                if job_title is not None:
                    j.job_title = job_title
                if target_pay_range is not None:
                    item["fit_eval"].pay_bounds.display_range = target_pay_range
                if source_url is not None:
                    j.source_url = source_url
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

    def fetch_all_opportunities(self, force_refresh: bool = False, require_fresh: bool = False) -> List[Dict[str, Any]]:
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
                "Job Description": "",
                "Raw JD Link": j.drive_jd_link or "",
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
                "Job Signals": TelemetryService.serialize_display_findings(fe),
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
            self.screening_qa_store = [item for item in self.screening_qa_store if item.get("qa_id") != q.qa_id]
            self.screening_qa_store.append({
                "qa_id": q.qa_id,
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

    def fetch_screening_qa(self, opportunity_id: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
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
    def __init__(self):
        self.is_connected = True
        self.workspaces = {}

    def create_application_workspace(self, company_name: str, job_title: str, opportunity_id: Optional[str] = None) -> Dict[str, str]:
        import uuid
        from datetime import datetime
        opportunity_id = opportunity_id or str(uuid.uuid4())
        for ws in self.workspaces.values():
            if ws.get("opportunity_id") == opportunity_id:
                return {k: ws[k] for k in ("folder_id", "folder_link", "opportunity_id")}
        folder_id = f"mock_folder_{uuid.uuid4().hex[:8]}"
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        self.workspaces[folder_id] = {
            "opportunity_id": opportunity_id,
            "folder_id": folder_id,
            "folder_link": folder_link,
            "folder_name": f"{company_name}_{job_title}_{datetime.now().strftime('%Y-%m-%d')}",
            "company": company_name,
            "title": job_title,
            "created_time": datetime.now().isoformat(),
            "status": "incomplete",
            "raw_jd_text": "",
            "files": [
                {"id": f"sc_{folder_id}", "name": "Pipeline Tracker (Master Sheet)", "mimeType": "application/vnd.google-apps.shortcut"}
            ]
        }
        return {"folder_id": folder_id, "folder_link": folder_link, "opportunity_id": opportunity_id}

    def ensure_workspace_opportunity_id(self, folder_id: str, opportunity_id: Optional[str] = None) -> str:
        stored = self.workspaces[folder_id]["opportunity_id"]
        if opportunity_id and opportunity_id != stored:
            raise ValueError("Conflicting workspace identity")
        return stored

    def save_ingestion_checkpoint(self, folder_id: str, payload: Dict[str, Any]) -> bool:
        self.workspaces[folder_id]["checkpoint"] = payload.copy()
        return True

    def fetch_ingestion_checkpoint(self, folder_id: str) -> Dict[str, Any]:
        return self.workspaces[folder_id].get("checkpoint", {}).copy()

    def upload_raw_job_description(self, folder_id: str, raw_text: str, company_name: str = "", job_title: str = "") -> Optional[Dict[str, str]]:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["raw_jd_text"] = raw_text
            self.workspaces[folder_id]["files"].append({
                "id": f"raw_jd_{folder_id}",
                "name": "Raw Job Description",
                "mimeType": "application/vnd.google-apps.document",
                "webViewLink": f"https://docs.google.com/document/d/mock_raw_{folder_id}/edit"
            })
        return {"file_id": f"mock_raw_jd_{folder_id}", "file_link": f"https://docs.google.com/document/d/mock_raw_{folder_id}/edit"}

    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["files"].append({
                "id": f"res_{folder_id}",
                "name": output_filename,
                "mimeType": "application/pdf"
            })
        return f"mock_pdf_{folder_id}"

    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["files"].append({
                "id": f"rep_{folder_id}",
                "name": os.path.basename(local_docx_path),
                "mimeType": "application/vnd.google-apps.document"
            })
        return f"mock_docx_{folder_id}"

    def create_screening_questions_doc(
        self,
        folder_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        opportunity_id: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["files"].append({
                "id": f"sq_{folder_id}",
                "name": "Screening Questions",
                "mimeType": "application/vnd.google-apps.document"
            })
        return {"file_id": f"mock_screening_doc_id", "file_link": "https://docs.google.com/document/d/mock_screening_questions/edit"}

    def fetch_incomplete_workspaces(self, completed_folder_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        from job_pipeline.domain.services import IngestionRecoveryService
        completed_set = set(completed_folder_ids or [])
        res = []
        for fid, ws in self.workspaces.items():
            if ws["status"] in ("complete", "trashed"):
                continue
            if fid in completed_set and ws["status"] != "incomplete":
                continue
            raw_text = ws.get("raw_jd_text", "")
            company = ws.get("company", "Target Company")
            title = ws.get("title", "Target Role")
            if not company or not title or company == "Target Company" or title == "Target Role":
                parsed_c, parsed_t = IngestionRecoveryService.parse_job_identity(raw_text, ws.get("folder_name", ""))
                company = parsed_c or company
                title = parsed_t or title
                ws["company"] = company
                ws["title"] = title

            preview = IngestionRecoveryService.extract_jd_preview(raw_text)
            date_disp = IngestionRecoveryService.format_created_date(ws.get("created_time"))
            res.append({
                "folder_id": fid,
                "folder_link": ws.get("folder_link"),
                "folder_name": ws.get("folder_name"),
                "company": company,
                "title": title,
                "created_time": ws.get("created_time"),
                "created_date_display": date_disp,
                "raw_jd_text": raw_text,
                "raw_jd_preview": preview,
                "existing_files": list(ws.get("files", []))
            })
        return res

    def mark_workspace_complete(self, folder_id: str) -> bool:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["status"] = "complete"
            return True
        return True

    def fetch_raw_job_description(self, folder_id: str) -> Optional[str]:
        if folder_id not in self.workspaces:
            raise RuntimeError("Workspace not found; cannot recover job description.")
        text = self.workspaces[folder_id].get("raw_jd_text")
        if not text or len(text.strip()) < 20:
            raise RuntimeError("This workspace's raw job description is missing or unreadable.")
        return text

    def delete_application_workspace(self, folder_id: str, canonical_opportunities: Optional[List[Dict[str, Any]]] = None) -> bool:
        from job_pipeline.domain.services import IngestionRecoveryService
        if canonical_opportunities is None or folder_id not in self.workspaces:
            return False
        ws = self.workspaces[folder_id]
        if IngestionRecoveryService.find_workspace_record(canonical_opportunities, folder_id, ws["opportunity_id"]):
            return False
        if ws["status"] == "incomplete":
            ws["status"] = "trashed"
            return True
        return False

    def list_workspace_files(self, folder_id: str) -> List[Dict[str, Any]]:
        if folder_id in self.workspaces:
            return list(self.workspaces[folder_id].get("files", []))
        return []

    def rename_application_workspace(self, folder_id: str, new_name: str) -> bool:
        if folder_id in self.workspaces:
            self.workspaces[folder_id]["folder_name"] = new_name
            return True
        return True



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
    def evaluate_job_signals(
        self,
        raw_jd: str,
        rules: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[Any], List[Any], List[Any]]:
        from job_pipeline.domain.telemetry_service import TelemetryService
        from job_pipeline.logger import log_job_signals

        if rules is None:
            try:
                from job_pipeline.domain.services import PipelineConfigService
                rules = PipelineConfigService.get_active_telemetry_rules()
            except Exception:
                rules = []

        normalized_rules = [TelemetryService.normalize_rule(r) for r in (rules or []) if (r.get("enabled", True) if isinstance(r, dict) else r.enabled)]
        deterministic_rules = [r for r in normalized_rules if (r.match_mode or "").lower() != "concept"]
        semantic_rules = [r for r in normalized_rules if (r.match_mode or "").lower() == "concept" and TelemetryService.validate_rule(r)[0]]

        det_findings = TelemetryService.evaluate_deterministic_rules(normalized_rules, raw_jd, tag="JOB SIGNALS")

        cache_key = TelemetryService.compute_cache_key(
            raw_jd,
            [r if isinstance(r, dict) else r.model_dump() for r in (rules or [])]
        )
        cache_key = "mock:dedicated-signals-v1:" + cache_key
        cached_res = TelemetryService.get_cached_extraction(cache_key)
        if cached_res is not None:
            total_findings = sum(len(g) for g in cached_res)
            log_job_signals(f"Dedicated semantic evaluation cache hit; reusing {total_findings} findings.")
            log_job_signals(f"Flags={len(cached_res[0])} Warnings={len(cached_res[1])} Benefits={len(cached_res[2])}.")
            return cached_res

        log_job_signals(f"Evaluating {len(semantic_rules)} semantic rules via dedicated LLM pass.")
        log_job_signals("Semantic matches returned=0, accepted=0, rejected=0.")

        flags, warns, benefits = TelemetryService.split_findings(det_findings)
        log_job_signals(f"Flags={len(flags)} Warnings={len(warns)} Benefits={len(benefits)}.")
        res = (flags, warns, benefits)
        TelemetryService.set_cached_extraction(cache_key, res)
        return res

    def extract_job_telemetry(
        self,
        raw_jd: str,
        warning_rules: Optional[List[Dict[str, Any]]] = None,
        pre_evaluated_findings: Optional[List[Any]] = None
    ) -> JobExtractionPayload:
        if warning_rules is None:
            try:
                from job_pipeline.domain.services import PipelineConfigService
                warning_rules = PipelineConfigService.get_active_telemetry_rules()
            except Exception:
                warning_rules = []

        from job_pipeline.domain.telemetry_service import TelemetryService
        if pre_evaluated_findings is not None:
            flags, warns, benefits = TelemetryService.split_findings(pre_evaluated_findings)
            detected_flags = [f.to_display_string() if hasattr(f, "to_display_string") else str(f) for f in flags]
            detected_warnings = [f.to_display_string() if hasattr(f, "to_display_string") else str(f) for f in warns]
            detected_benefits = [f.to_display_string() if hasattr(f, "to_display_string") else str(f) for f in benefits]
        else:
            normalized_rules = [TelemetryService.normalize_rule(r) for r in (warning_rules or []) if (r.get("enabled", True) if isinstance(r, dict) else r.enabled)]
            deterministic_findings = TelemetryService.evaluate_deterministic_rules(normalized_rules, raw_jd)
            det_flags, det_warns, det_benefits = TelemetryService.split_findings(deterministic_findings)

            detected_flags = [f.to_display_string() for f in det_flags]
            detected_warnings = [f.to_display_string() for f in det_warns]
            detected_benefits = [f.to_display_string() for f in det_benefits]

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
                telemetry_warnings=detected_warnings,
                telemetry_flags=detected_flags,
                telemetry_benefits=detected_benefits
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
