import os
import re
import uuid
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import JobPosting
from job_pipeline.ports.email_port import EmailIngestionPort


class GmailIngestionAdapter(EmailIngestionPort):
    """Secondary Driven Adapter for Gmail Job Alert Ingestion and Recruiter Email Parsing."""

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    def fetch_job_alert_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Returns mock/live job alert email payloads."""
        return [
            {
                "id": "msg_linkedin_101",
                "subject": "LinkedIn Job Alert: Senior Revenue Operations Analyst at Snowflake",
                "sender": "jobalerts-noreply@linkedin.com",
                "body": (
                    "New Job Recommendation: Snowflake is hiring a Lead Revenue Operations Analyst in San Francisco, CA (Remote). "
                    "Salary range: $130,000 - $180,000. Required: Salesforce, SQL, dbt, Tableau. "
                    "Apply here: https://www.linkedin.com/jobs/view/10009988"
                )
            }
        ]

    def parse_job_alert_to_opportunity(self, email_message: Dict[str, Any]) -> Optional[JobPosting]:
        subject = email_message.get("subject", "")
        body = email_message.get("body", "")

        company_match = re.search(r'at ([A-Za-z0-9\s]+)', subject)
        company = company_match.group(1).strip() if company_match else "Job Alert Company"

        title_match = re.search(r'Alert:\s*(.*?)\s*at', subject)
        title = title_match.group(1).strip() if title_match else "Job Alert Role"

        url_match = re.search(r'https?://[^\s]+', body)
        source_url = url_match.group(0) if url_match else None

        return JobPosting(
            opportunity_id=str(uuid.uuid4()),
            company_name=company,
            job_title=title,
            title_family="revenue_operations",
            raw_description=body,
            source_url=source_url,
            status="Pending"
        )
