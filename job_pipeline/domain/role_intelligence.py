"""Domain logic for Role Intelligence source bundle preparation and deferred generation."""

from __future__ import annotations

import copy
import os
import re
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, Union

from job_pipeline.domain.models import (
    INTERVIEW_STAGES,
    ROLE_INTELLIGENCE_STATUS_NOT_GENERATED,
    ROLE_INTELLIGENCE_STATUS_GENERATING,
    ROLE_INTELLIGENCE_STATUS_GENERATED,
    ROLE_INTELLIGENCE_STATUS_FAILED,
    JobPosting,
)
from job_pipeline.logger import log_llm, log_error, log_action


def tag_text(text: str, prefix: str) -> str:
    """Tag non-empty source lines with stable, human-readable IDs (e.g., [J001], [R001])."""
    tagged: list[str] = []
    i = 0
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        i += 1
        tagged.append(f"[{prefix}{i:03d}] {line}")
    return "\n".join(tagged)


def prepare_source_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate and enrich job and resume payloads with stable line-tag provenance."""
    out = copy.deepcopy(bundle)
    job = out.setdefault("job", {})
    resume = out.setdefault("resume", {})

    if not str(job.get("description", "")).strip():
        raise ValueError("job.description is required")
    if not str(resume.get("text", "")).strip():
        raise ValueError("resume.text is required")

    job["tagged_description"] = tag_text(job["description"], "J")
    resume["tagged_text"] = tag_text(resume["text"], "R")
    return out


def has_role_intelligence(opp: Union[Dict[str, Any], JobPosting, Any]) -> bool:
    """Checks whether Role Intelligence already exists for this application."""
    if isinstance(opp, JobPosting):
        if opp.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_GENERATED:
            return True
        if opp.role_intelligence_link:
            return True
        opp_id = opp.opportunity_id
        company = opp.company_name
    elif isinstance(opp, dict):
        status = opp.get("Role Intelligence Status") or opp.get("role_intelligence_status")
        if status == ROLE_INTELLIGENCE_STATUS_GENERATED:
            return True
        link = (
            opp.get("Role Intelligence Link") or opp.get("role_intelligence_link") or
            opp.get("Role Intelligence Report Link") or opp.get("role_intelligence_report_link") or
            opp.get("Role Intelligence Doc Link") or opp.get("role_intelligence_doc_link")
        )
        if link and str(link).strip():
            return True
        opp_id = opp.get("Opportunity ID") or opp.get("opportunity_id")
        company = opp.get("Company Name") or opp.get("company_name")
    else:
        opp_id = getattr(opp, "opportunity_id", None)
        company = getattr(opp, "company_name", None)

    # Check local report existence by UUID5
    if opp_id:
        try:
            uuid_hex = uuid.uuid5(uuid.NAMESPACE_URL, str(opp_id)).hex
            local_path = Path("output_reports") / uuid_hex / "Role_Intelligence_Report.docx"
            if local_path.exists():
                return True
        except Exception:
            pass

    # Check local report existence by legacy company name
    if company:
        clean_company = str(company).replace(" ", "_")
        legacy_path = Path("output_reports") / f"{clean_company}_Role_Intelligence_Report.docx"
        if legacy_path.exists():
            return True

    return False


def get_role_intelligence_status(opp: Union[Dict[str, Any], JobPosting, Any]) -> str:
    """Returns explicit or inferred Role Intelligence status:
    'Not Generated', 'Generating', 'Generated', or 'Failed'.
    """
    if isinstance(opp, JobPosting):
        raw_status = opp.role_intelligence_status
    elif isinstance(opp, dict):
        raw_status = opp.get("Role Intelligence Status") or opp.get("role_intelligence_status")
    else:
        raw_status = getattr(opp, "role_intelligence_status", None)

    if raw_status in (
        ROLE_INTELLIGENCE_STATUS_GENERATED,
        ROLE_INTELLIGENCE_STATUS_GENERATING,
        ROLE_INTELLIGENCE_STATUS_FAILED,
        ROLE_INTELLIGENCE_STATUS_NOT_GENERATED,
    ):
        return raw_status

    # Backward compatibility: infer from existing artifacts
    if has_role_intelligence(opp):
        return ROLE_INTELLIGENCE_STATUS_GENERATED

    return ROLE_INTELLIGENCE_STATUS_NOT_GENERATED


def get_local_report_path(opportunity_id: str, company_name: Optional[str] = None) -> Path:
    """Returns the canonical or legacy path where the Role Intelligence DOCX artifact is stored."""
    if opportunity_id:
        try:
            uuid_hex = uuid.uuid5(uuid.NAMESPACE_URL, str(opportunity_id)).hex
            canonical_path = Path("output_reports") / uuid_hex / "Role_Intelligence_Report.docx"
            if canonical_path.exists():
                return canonical_path
        except Exception:
            pass

    if company_name:
        clean_comp = str(company_name).replace(" ", "_")
        legacy_path = Path("output_reports") / f"{clean_comp}_Role_Intelligence_Report.docx"
        if legacy_path.exists():
            return legacy_path

    uuid_hex = uuid.uuid5(uuid.NAMESPACE_URL, str(opportunity_id)).hex if opportunity_id else "default"
    return Path("output_reports") / uuid_hex / "Role_Intelligence_Report.docx"


def should_trigger_role_intelligence(
    previous_stage: str,
    new_stage: str,
    opp: Union[Dict[str, Any], JobPosting, Any]
) -> bool:
    """
    Determines whether Role Intelligence should be automatically triggered on stage change.
    Triggers only when moving from a non-interview stage into an interview stage
    and Role Intelligence has not yet been generated.
    """
    is_new_interview_stage = new_stage in INTERVIEW_STAGES
    was_already_interview_stage = previous_stage in INTERVIEW_STAGES

    if not is_new_interview_stage or was_already_interview_stage:
        return False

    return not has_role_intelligence(opp)


class RoleIntelligenceService:
    """Service for deferred, on-demand Role Intelligence generation."""

    @staticmethod
    def generate_for_opportunity(
        *,
        opportunity_id: str,
        company_name: str,
        job_title: str,
        raw_description: Optional[str] = None,
        title_family: Optional[str] = None,
        target_pay_bounds: Optional[Dict[str, Any]] = None,
        drive_folder_id: Optional[str] = None,
        drive_folder_link: Optional[str] = None,
        selected_resume_name: Optional[str] = None,
        llm_adapter: Any,
        drive_adapter: Optional[Any] = None,
        resume_repo: Optional[Any] = None,
        storage_adapter: Optional[Any] = None,
        demo_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes Role Intelligence for an existing application.
        Decoupled from ingestion; callable on automatic interview stage transitions or manual triggers.
        """
        clean_company = (company_name or "Target Company").strip()
        clean_title = (job_title or "Target Role").strip()

        # Logging requirement: [LLM] Generating Role Intelligence for '<company>'...
        log_llm(f"Generating Role Intelligence for '{clean_company}'...")

        # Resolve Drive folder ID if needed
        folder_id = drive_folder_id
        if not folder_id and drive_folder_link:
            m = re.search(r"(?:folders/|[?&]id=)([\w-]+)", str(drive_folder_link))
            if m:
                folder_id = m.group(1)

        # Resolve raw job description
        jd_text = raw_description or ""
        if not jd_text or len(jd_text.strip()) < 20:
            if drive_adapter and folder_id:
                try:
                    fetched_jd = drive_adapter.fetch_raw_job_description(folder_id)
                    if fetched_jd and len(fetched_jd.strip()) >= 20:
                        jd_text = fetched_jd
                except Exception:
                    pass

            if not jd_text or len(jd_text.strip()) < 20:
                if drive_adapter and folder_id:
                    try:
                        ckpt = drive_adapter.fetch_ingestion_checkpoint(folder_id)
                        if ckpt and ckpt.get("jd_text"):
                            jd_text = ckpt["jd_text"]
                    except Exception:
                        pass

            if not jd_text or len(jd_text.strip()) < 20:
                if opportunity_id:
                    try:
                        u_hex = uuid.uuid5(uuid.NAMESPACE_URL, str(opportunity_id)).hex
                        u_path = Path("output_reports") / u_hex / "Raw_JD.txt"
                        if u_path.exists():
                            jd_text = u_path.read_text(encoding="utf-8")
                    except Exception:
                        pass

            if not jd_text or len(jd_text.strip()) < 20:
                backup_path = Path("output_reports") / f"{clean_company.replace(' ', '_')}_Raw_JD.txt"
                if backup_path.exists():
                    try:
                        jd_text = backup_path.read_text(encoding="utf-8")
                    except Exception:
                        pass

        if not jd_text or len(jd_text.strip()) < 20:
            raise ValueError(f"Job description is unavailable for '{clean_company}'. Cannot generate Role Intelligence.")

        # Resolve resume
        selected_resume = None
        if resume_repo:
            try:
                selected_resume = resume_repo.select_best_fit_resume(clean_title, title_family or "revenue_operations")
            except Exception:
                pass

        resume_id = selected_resume.doc_id if selected_resume and getattr(selected_resume, "doc_id", None) else "res1"
        resume_text = ""
        if resume_repo and getattr(selected_resume, "doc_id", None):
            try:
                resume_text = resume_repo.fetch_resume_text(selected_resume.doc_id)
            except Exception:
                resume_text = ""

        # Determine output path
        uuid_hex = uuid.uuid5(uuid.NAMESPACE_URL, str(opportunity_id)).hex
        output_dir = Path("output_reports") / uuid_hex
        output_dir.mkdir(parents=True, exist_ok=True)
        docx_filename = "Role_Intelligence_Report.docx"
        output_docx_path = str(output_dir / docx_filename)

        # Call LLM adapter
        pay_bounds = target_pay_bounds or {}
        report = llm_adapter.generate_role_intelligence_report(
            job_data={"company": clean_company, "title": clean_title, "description": jd_text},
            resume_data={"resume_id": resume_id, "text": resume_text},
            output_docx_path=output_docx_path,
            target_pay_bounds=pay_bounds,
            demo_mode=demo_mode
        )

        # Upload to Google Drive if connected and folder exists
        report_link = output_docx_path
        if drive_adapter and folder_id:
            try:
                file_id = drive_adapter.upload_role_intelligence_report(folder_id, output_docx_path)
                if file_id:
                    report_link = f"https://docs.google.com/document/d/{file_id}/edit"
            except Exception as up_err:
                log_error(f"Failed to upload Role Intelligence report to Google Drive: {up_err}")

        # Update persistence if storage adapter provided
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        tokens = getattr(llm_adapter, "last_report_tokens", 0)
        if storage_adapter and hasattr(storage_adapter, "update_role_intelligence_status"):
            try:
                storage_adapter.update_role_intelligence_status(
                    opportunity_id=opportunity_id,
                    status=ROLE_INTELLIGENCE_STATUS_GENERATED,
                    report_link=report_link,
                    generated_at=now_iso,
                    tokens_used=tokens
                )
            except Exception as st_err:
                log_error(f"Failed to update storage with Role Intelligence status: {st_err}")

        return {
            "status": ROLE_INTELLIGENCE_STATUS_GENERATED,
            "report_link": report_link,
            "output_docx_path": output_docx_path,
            "generated_at": now_iso,
            "report": report
        }
