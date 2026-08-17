import os
import uuid
import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from job_pipeline.domain.models import JobPosting, FitEvaluation, TargetPayBounds
from job_pipeline.ports.storage_port import JobStoragePort


def to_postgres_array(lst: List[str]) -> str:
    """Formats a Python list of strings as a Postgres text array literal, e.g. {'Python', 'Postgres'}."""
    if not lst:
        return "{}"
    escaped_items = []
    for item in lst:
        clean_item = item.replace("'", "''")
        escaped_items.append(f"'{clean_item}'")
    return "{" + ", ".join(escaped_items) + "}"


class GoogleSheetsAdapter(JobStoragePort):
    """Secondary Driven Adapter for Google Sheets ('Raw Ingestion' & 'Requirements Extraction')."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None
    ):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
        self.spreadsheet_id = spreadsheet_id or os.environ.get("GOOGLE_SPREADSHEET_ID", "your-google-spreadsheet-id-here")
        self._client = None
        self._spreadsheet = None
        self._init_connection()

    def _init_connection(self):
        if not os.path.exists(self.credentials_path):
            print(f"WARNING: Credentials file '{self.credentials_path}' not found. Google Sheets adapter disabled.")
            return

        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, scope)
            self._client = gspread.authorize(creds)
            self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
        except Exception as e:
            print(f"WARNING: Could not connect to Google Sheets: {e}")

    @property
    def is_connected(self) -> bool:
        return self._spreadsheet is not None

    def fetch_pending_jobs(self) -> List[JobPosting]:
        if not self.is_connected:
            return []

        try:
            worksheet = self._spreadsheet.worksheet("Raw Ingestion")
            records = worksheet.get_all_records()
            pending_jobs = []

            for idx, rec in enumerate(records, start=2):
                status = str(rec.get("Status", "")).strip()
                raw_jd = str(rec.get("Job Description", "")).strip()

                if status not in ["Processed", "Failed", "Flagged: Dealbreaker"] and len(raw_jd) >= 20:
                    opp_id = str(rec.get("Opportunity ID", "")).strip() or str(uuid.uuid4())
                    pending_jobs.append(JobPosting(
                        opportunity_id=opp_id,
                        company_name=str(rec.get("Company Name", "")).strip(),
                        job_title=str(rec.get("Job Title", "")).strip(),
                        title_family=str(rec.get("Title Family", "revenue_operations")).strip(),
                        raw_description=raw_jd,
                        source_url=str(rec.get("Source URL", "")).strip() or None,
                        status=status or "Pending",
                        row_index=idx
                    ))

            return pending_jobs
        except Exception as e:
            print(f"ERROR: Failed to fetch pending jobs from Google Sheets: {e}")
            return []

    def save_opportunity(self, job: JobPosting, fit_eval: FitEvaluation) -> bool:
        if not self.is_connected:
            return False

        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            headers = [h.strip() for h in ingest_ws.row_values(1)]

            # Ensure required columns exist
            required_cols = ["Opportunity ID", "Tokens", "Fit Warning", "Selected Resume", "Target Pay Range", "Drive Folder Link"]
            for col in required_cols:
                if col not in headers:
                    ingest_ws.update_cell(1, len(headers) + 1, col)
                    headers.append(col)

            header_indices = {header: idx + 1 for idx, header in enumerate(headers)}
            records = ingest_ws.get_all_records()

            # Find matching row by exact row_index or Opportunity ID or Company+Title
            target_row_idx = job.row_index
            if not target_row_idx:
                for idx, rec in enumerate(records, start=2):
                    if str(rec.get("Opportunity ID", "")).strip() == job.opportunity_id:
                        target_row_idx = idx
                        break
                    if str(rec.get("Company Name", "")).strip() == job.company_name and str(rec.get("Job Title", "")).strip() == job.job_title:
                        target_row_idx = idx
                        break

            if not target_row_idx:
                target_row_idx = len(records) + 2

            cell_updates = []

            def queue(header, val):
                c_idx = header_indices.get(header)
                if c_idx:
                    cell_updates.append(gspread.Cell(row=target_row_idx, col=c_idx, value=val))

            queue("Company Name", job.company_name)
            queue("Job Title", job.job_title)
            queue("Title Family", job.title_family)
            queue("Date Created", job.date_created)
            if job.source_url:
                queue("Source URL", job.source_url)
            queue("Opportunity ID", job.opportunity_id)
            if job.tokens_used:
                queue("Tokens", f"{job.tokens_used:,}")
            queue("Fit Warning", fit_eval.reasoning)
            if job.selected_resume_name:
                queue("Selected Resume", job.selected_resume_name)
            queue("Target Pay Range", fit_eval.pay_bounds.display_range)
            if job.drive_folder_link:
                queue("Drive Folder Link", job.drive_folder_link)

            final_status = "Processed" if fit_eval.is_qualified else fit_eval.status
            queue("Status", final_status)
            queue("Last Modified", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            ingest_ws.update_cells(cell_updates)

            # Update Requirements Extraction worksheet (gid=1967659859)
            req_sheet_name = "Requirements Extraction"
            try:
                extraction_ws = self._spreadsheet.worksheet(req_sheet_name)
            except Exception:
                extraction_ws = self._spreadsheet.add_worksheet(title=req_sheet_name, rows=1000, cols=11)
                req_headers = [
                    "requirement_id", "opportunity_id", "years_experience_required",
                    "required_tech_stack", "preferred_tech_stack", "core_pain_points",
                    "is_remote", "salary_min", "salary_max", "extraction_confidence", "updated_at"
                ]
                extraction_ws.append_row(req_headers)

            req_row = [
                str(uuid.uuid4()),
                job.opportunity_id,
                "",
                to_postgres_array(job.required_skills),
                to_postgres_array(job.preferred_skills),
                fit_eval.reasoning,
                "FALSE",
                fit_eval.pay_bounds.posted_min if fit_eval.pay_bounds.posted_min is not None else "",
                fit_eval.pay_bounds.posted_max if fit_eval.pay_bounds.posted_max is not None else "",
                1.0,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]
            req_cell_updates = [gspread.Cell(row=target_row_idx, col=col_idx, value=val) for col_idx, val in enumerate(req_row, start=1)]
            extraction_ws.update_cells(req_cell_updates)

            print(f"SUCCESS: Saved job opportunity '{job.company_name} - {job.job_title}' to Google Sheets.")
            return True
        except Exception as e:
            print(f"ERROR: Failed to save opportunity to Google Sheets: {e}")
            return False

    def update_opportunity_status(self, opportunity_id: str, status: str, notes: Optional[str] = None) -> bool:
        if not self.is_connected:
            return False
        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            records = ingest_ws.get_all_records()
            headers = [h.strip() for h in ingest_ws.row_values(1)]
            status_col = headers.index("Status") + 1 if "Status" in headers else 5

            for idx, rec in enumerate(records, start=2):
                if str(rec.get("Opportunity ID", "")).strip() == opportunity_id:
                    ingest_ws.update_cell(idx, status_col, status)
                    return True
            return False
        except Exception as e:
            print(f"ERROR: Failed to update status in Google Sheets: {e}")
            return False
