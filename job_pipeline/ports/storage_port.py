from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting, FitEvaluation


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


class DocumentStoragePort(ABC):
    """Abstract Port for managing application asset folders in Google Drive / Storage."""

    @abstractmethod
    def create_application_workspace(self, company_name: str, job_title: str) -> Dict[str, str]:
        """Creates an application folder and returns {'folder_id': ..., 'folder_link': ...}."""
        pass

    @abstractmethod
    def upload_raw_job_description(self, folder_id: str, raw_text: str) -> Optional[str]:
        pass

    @abstractmethod
    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        pass

    @abstractmethod
    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        pass
