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
    def update_opportunity_status(self, opportunity_id: str, status: str, notes: Optional[str] = None) -> bool:
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
