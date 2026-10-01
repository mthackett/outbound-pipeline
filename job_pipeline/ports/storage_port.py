from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting, FitEvaluation, ScreeningQA


class JobStoragePort(ABC):
    """Abstract Port for saving and querying job application records."""

    @abstractmethod
    def fetch_pending_jobs(self) -> List[JobPosting]:
        pass

    @abstractmethod
    def save_opportunity(self, job: JobPosting, fit_eval: FitEvaluation) -> bool:
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def fetch_all_opportunities(self) -> List[Dict[str, Any]]:
        """Retrieves all tracked opportunities for CRM, pipeline viewing, and guardrail checks."""
        pass

    @abstractmethod
    def save_screening_qa(
        self,
        opportunity_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        gdoc_link: Optional[str] = None
    ) -> bool:
        """Saves screening questions and answers to structured storage."""
        pass

    @abstractmethod
    def fetch_screening_qa(self, opportunity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches screening questions and answers."""
        pass

    @abstractmethod
    def append_call_note(self, opportunity_id: str, note_text: str, call_type: str = "Call", interviewer: str = "") -> bool:
        """Appends a timestamped call or interview note to an opportunity."""
        pass

    @abstractmethod
    def update_opportunity_screening_doc(self, opportunity_id: str, gdoc_link: str, qa_count: int) -> bool:
        """Updates screening doc link and QA count for an opportunity in the main tracker."""
        pass


class DocumentStoragePort(ABC):
    """Abstract Port for managing application asset folders in Google Drive / Storage."""

    @abstractmethod
    def create_application_workspace(self, company_name: str, job_title: str) -> Dict[str, str]:
        """Creates an application folder and returns {'folder_id': ..., 'folder_link': ...}."""
        pass

    @abstractmethod
    def upload_raw_job_description(self, folder_id: str, raw_text: str, company_name: str = "", job_title: str = "") -> Optional[Dict[str, str]]:
        pass

    @abstractmethod
    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        pass

    @abstractmethod
    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        pass

    @abstractmethod
    def create_screening_questions_doc(
        self,
        folder_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        opportunity_id: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Creates a Google Doc titled 'Screening Questions' inside the application folder."""
        pass

    @abstractmethod
    def fetch_incomplete_workspaces(self, completed_folder_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Finds any workspaces that were created but have not yet been marked complete or logged to canonical storage."""
        pass

    @abstractmethod
    def mark_workspace_complete(self, folder_id: str) -> bool:
        """Marks a workspace as successfully completed."""
        pass

    @abstractmethod
    def fetch_raw_job_description(self, folder_id: str) -> Optional[str]:
        """Fetches persisted raw job description text from workspace folder."""
        pass

    @abstractmethod
    def delete_application_workspace(self, folder_id: str) -> bool:
        """Deletes workspace folder and owned artifacts without deleting referenced resources."""
        pass

    @abstractmethod
    def list_workspace_files(self, folder_id: str) -> List[Dict[str, Any]]:
        """Lists existing files in workspace folder."""
        pass

    @abstractmethod
    def rename_application_workspace(self, folder_id: str, new_name: str) -> bool:
        """Renames an existing application workspace folder."""
        pass

