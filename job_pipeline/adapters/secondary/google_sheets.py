import os
import time
import uuid
import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

import gspread

from job_pipeline.adapters.secondary.google_auth import get_google_credentials
from job_pipeline.domain.models import JobPosting, FitEvaluation, TargetPayBounds, ScreeningQA
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
        self.spreadsheet_id = spreadsheet_id or os.environ.get("GOOGLE_SPREADSHEET_ID", "")
        self._client = None
        self._spreadsheet = None
        self.auth_type = "none"
        self._cached_opportunities = None
        self._opportunities_cache_time = 0
        self._cached_screening_qa = None
        self._screening_qa_cache_time = 0
        self._cache_ttl_seconds = 120
        self._init_connection()

    def _init_connection(self):
        if not self.spreadsheet_id:
            print("WARNING: GOOGLE_SPREADSHEET_ID is not configured.")
            return

        creds, auth_type = get_google_credentials(credentials_path=self.credentials_path)
        self.auth_type = auth_type

        if creds is None:
            print(f"WARNING: No valid Google credentials found (checked OAuth token.json and '{self.credentials_path}'). Google Sheets adapter disabled.")
            return

        try:
            self._client = gspread.authorize(creds)
            self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
            print(f"INFO: Google Sheets Adapter initialized successfully (Auth Type: {self.auth_type}).")
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
            required_cols = [
                "Opportunity ID", "Tokens", "Fit Warning", "Selected Resume",
                "Target Pay Range", "Drive Folder Link", "Screening Doc Link", "Screening QA Count"
            ]
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
            if job.drive_screening_doc_link:
                queue("Screening Doc Link", job.drive_screening_doc_link)
            if job.screening_qa:
                queue("Screening QA Count", len(job.screening_qa))

            final_status = "Processed" if fit_eval.is_qualified else fit_eval.status
            queue("Status", final_status)
            queue("Last Modified", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            ingest_ws.update_cells(cell_updates)

            # Invalidate cached opportunities
            self._cached_opportunities = None

            # Save Screening QA if present
            if job.screening_qa:
                self.save_screening_qa(
                    opportunity_id=job.opportunity_id,
                    company_name=job.company_name,
                    job_title=job.job_title,
                    qa_items=job.screening_qa,
                    gdoc_link=job.drive_screening_doc_link
                )

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

    def save_screening_qa(
        self,
        opportunity_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        gdoc_link: Optional[str] = None
    ) -> bool:
        """Saves screening questions and answers to 'Screening QA' worksheet."""
        if not self.is_connected or not qa_items:
            return False
        try:
            qa_sheet_name = "Screening QA"
            try:
                qa_ws = self._spreadsheet.worksheet(qa_sheet_name)
            except Exception:
                qa_ws = self._spreadsheet.add_worksheet(title=qa_sheet_name, rows=1000, cols=9)
                headers = [
                    "qa_id", "opportunity_id", "company_name", "job_title",
                    "question", "answer", "category", "timestamp", "gdoc_link"
                ]
                qa_ws.append_row(headers)

            rows_to_append = []
            for item in qa_items:
                rows_to_append.append([
                    str(uuid.uuid4()),
                    opportunity_id,
                    company_name,
                    job_title,
                    item.question,
                    item.answer,
                    item.category or "",
                    item.created_at,
                    gdoc_link or ""
                ])

            if rows_to_append:
                qa_ws.append_rows(rows_to_append)
            self._cached_screening_qa = None
            print(f"SUCCESS: Appended {len(rows_to_append)} screening Q&As to Google Sheets.")
            return True
        except Exception as e:
            print(f"ERROR: Failed to save screening QA to Google Sheets: {e}")
            return False

    def fetch_screening_qa(self, opportunity_id: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Retrieves all screening questions or questions for a specific opportunity with TTL caching."""
        if not self.is_connected:
            return []
        now = time.time()
        if not force_refresh and self._cached_screening_qa is not None and (now - self._screening_qa_cache_time < self._cache_ttl_seconds):
            records = self._cached_screening_qa
        else:
            try:
                qa_ws = self._spreadsheet.worksheet("Screening QA")
                records = qa_ws.get_all_records()
                self._cached_screening_qa = records
                self._screening_qa_cache_time = now
            except Exception as e:
                if "429" in str(e) or "Quota exceeded" in str(e):
                    print("WARNING: Google Sheets read quota reached. Serving cached screening QA if available.")
                    if self._cached_screening_qa is not None:
                        records = self._cached_screening_qa
                    else:
                        return []
                else:
                    print(f"INFO: Screening QA worksheet notice: {e}")
                    return []
        if opportunity_id:
            return [r for r in records if str(r.get("opportunity_id", "")).strip() == opportunity_id]
        return records

    def update_opportunity_status(self, opportunity_id: str, status: str, notes: Optional[str] = None) -> bool:
        if not self.is_connected:
            return False
        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            records = ingest_ws.get_all_records()
            headers = [h.strip() for h in ingest_ws.row_values(1)]
            status_col = headers.index("Status") + 1 if "Status" in headers else 7
            notes_col = headers.index("Notes") + 1 if "Notes" in headers else None

            for idx, rec in enumerate(records, start=2):
                if str(rec.get("Opportunity ID", "")).strip() == opportunity_id:
                    ingest_ws.update_cell(idx, status_col, status)
                    if notes is not None and notes_col:
                        ingest_ws.update_cell(idx, notes_col, notes)
                    self._cached_opportunities = None
                    return True
            return False
        except Exception as e:
            print(f"ERROR: Failed to update status in Google Sheets: {e}")
            return False

    def append_call_note(self, opportunity_id: str, note_text: str, call_type: str = "Call", interviewer: str = "") -> bool:
        """Appends a timestamped call or interview note to an opportunity in 'Raw Ingestion'."""
        if not self.is_connected or not note_text:
            return False
        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            records = ingest_ws.get_all_records()
            headers = [h.strip() for h in ingest_ws.row_values(1)]
            notes_col = headers.index("Notes") + 1 if "Notes" in headers else None
            if not notes_col:
                return False

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            who = f" (with {interviewer.strip()})" if interviewer and interviewer.strip() else ""
            formatted_entry = f"[{timestamp} - {call_type}{who}]: {note_text.strip()}"

            for idx, rec in enumerate(records, start=2):
                if str(rec.get("Opportunity ID", "")).strip() == opportunity_id:
                    existing_notes = str(rec.get("Notes", "")).strip()
                    combined_notes = f"{existing_notes}\n{formatted_entry}" if existing_notes else formatted_entry
                    ingest_ws.update_cell(idx, notes_col, combined_notes)
                    self._cached_opportunities = None
                    return True
            return False
        except Exception as e:
            print(f"ERROR: Failed to append call note in Google Sheets: {e}")
            return False

    def update_opportunity_screening_doc(self, opportunity_id: str, gdoc_link: str, qa_count: int) -> bool:
        """Updates screening doc link and QA count for an opportunity in 'Raw Ingestion'."""
        if not self.is_connected or not opportunity_id:
            return False
        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            records = ingest_ws.get_all_records()
            headers = [h.strip() for h in ingest_ws.row_values(1)]
            doc_col = headers.index("Screening Doc Link") + 1 if "Screening Doc Link" in headers else None
            count_col = headers.index("Screening QA Count") + 1 if "Screening QA Count" in headers else None

            for idx, rec in enumerate(records, start=2):
                if str(rec.get("Opportunity ID", "")).strip() == opportunity_id:
                    if doc_col and gdoc_link:
                        ingest_ws.update_cell(idx, doc_col, gdoc_link)
                    if count_col and qa_count is not None:
                        ingest_ws.update_cell(idx, count_col, qa_count)
                    self._cached_opportunities = None
                    return True
            return False
        except Exception as e:
            print(f"ERROR: Failed to update screening doc link in Google Sheets: {e}")
            return False

    def fetch_all_opportunities(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Retrieves all tracked opportunities from 'Raw Ingestion' worksheet with TTL caching."""
        if not self.is_connected:
            return []
        now = time.time()
        if not force_refresh and self._cached_opportunities is not None and (now - self._opportunities_cache_time < self._cache_ttl_seconds):
            return self._cached_opportunities
        try:
            worksheet = self._spreadsheet.worksheet("Raw Ingestion")
            records = worksheet.get_all_records()
            self._cached_opportunities = records
            self._opportunities_cache_time = now
            return records
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                print("WARNING: Google Sheets read quota reached. Serving cached opportunities.")
                if self._cached_opportunities is not None:
                    return self._cached_opportunities
            print(f"ERROR: Failed to fetch opportunities from Google Sheets: {e}")
            return self._cached_opportunities or []
