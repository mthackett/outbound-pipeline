from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting


class EmailIngestionPort(ABC):
    """Abstract Port for parsing job alert emails (LinkedIn, Indeed, ZipRecruiter) and recruiter email threads."""

    @abstractmethod
    def fetch_job_alert_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def parse_job_alert_to_opportunity(self, email_message: Dict[str, Any]) -> Optional[JobPosting]:
        pass
