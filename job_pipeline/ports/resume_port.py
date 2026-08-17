from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class ResumeFileRef(BaseModel):
    doc_id: str
    filename: str
    role_label: str = ""


class ResumeRepositoryPort(ABC):
    """Abstract Port for candidate resume repositories and title-based routing."""

    @abstractmethod
    def list_available_resumes(self) -> List[ResumeFileRef]:
        """Lists candidate resume documents from storage (e.g. Google Drive folder)."""
        pass

    @abstractmethod
    def fetch_resume_text(self, doc_id: str) -> str:
        """Fetches plain text content of a resume document."""
        pass

    @abstractmethod
    def select_best_fit_resume(self, job_title: str, title_family: str) -> Optional[ResumeFileRef]:
        """Selects the best-fit resume file reference for a job title and family."""
        pass
