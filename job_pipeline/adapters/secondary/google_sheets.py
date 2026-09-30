import os
import time
import uuid
import json
import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

import socket
# Set default socket timeout to prevent any indefinite hangs on dead connections
socket.setdefaulttimeout(25)

import gspread

from job_pipeline.logger import log_sheets, log_warn, log_error, log_timed_action
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
        self._headers_cache = None
        self._init_connection()

    def _init_connection(self):
        if not self.spreadsheet_id:
            log_warn("GOOGLE_SPREADSHEET_ID is not configured.")
            return

        from job_pipeline.adapters.secondary.google_auth import get_google_auth_context
        self.auth_context = get_google_auth_context(credentials_path=self.credentials_path)
        self.auth_type = self.auth_context.mode
        creds = self.auth_context.credentials

        if not self.auth_context.can_access_configured_sheet:
            log_warn(f"No valid Google credentials found (checked OAuth token.json and '{self.credentials_path}'). Google Sheets adapter disabled.")
            return

        try:
            with log_timed_action(f"Connecting to Google Spreadsheet (ID: {self.spreadsheet_id[:8]}...)", tag="SHEETS"):
                self._client = gspread.authorize(creds)
                self._client.set_timeout(25)
                self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
            log_sheets(f"Google Sheets Adapter connected (Title: '{self._spreadsheet.title}', Auth Mode: {self.auth_type}).")
        except Exception as e:
            log_warn(f"Could not connect to Google Sheets: {e}")

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
                "Target Pay Range", "Drive Folder Link", "Screening Doc Link", "Screening QA Count",
                "Stage History", "Category", "Applied Via", "Priority",
                "Employment Arrangement", "Worker Classification", "Pay Basis",
                "Contract Duration", "Contract Value", "Staffing Agency",
                "Client Company", "Extension Possible", "FTE Conversion"
            ]
            missing_cols = [col for col in required_cols if col not in headers]
            if missing_cols:
                needed_total = len(headers) + len(missing_cols)
                if needed_total > ingest_ws.col_count:
                    ingest_ws.add_cols(needed_total - ingest_ws.col_count + 5)
                header_cells = [
                    gspread.Cell(row=1, col=len(headers) + 1 + i, value=col_name)
                    for i, col_name in enumerate(missing_cols)
                ]
                ingest_ws.update_cells(header_cells)
                headers.extend(missing_cols)

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

            # Contract & Arrangement attributes
            if job.employment_arrangement:
                queue("Employment Arrangement", job.employment_arrangement)
            if job.worker_classification:
                queue("Worker Classification", job.worker_classification)
            if job.pay_basis:
                queue("Pay Basis", job.pay_basis)
            if job.contract_length_raw:
                queue("Contract Duration", job.contract_length_raw)
            c_val = job.contract_value_display or (fit_eval.pay_bounds.contract_value_display if fit_eval and fit_eval.pay_bounds else None)
            if c_val:
                queue("Contract Value", c_val)
            if job.staffing_agency:
                queue("Staffing Agency", job.staffing_agency)
            if job.client_company:
                queue("Client Company", job.client_company)
            if job.extension_possible is not None:
                queue("Extension Possible", "Yes" if job.extension_possible else "No")
            if job.fte_conversion_possible is not None:
                queue("FTE Conversion", "Yes" if job.fte_conversion_possible else "No")

            final_status = "Processed" if fit_eval.is_qualified else fit_eval.status
            queue("Status", final_status)
            if job.category:
                queue("Category", job.category)
            if job.applied_via:
                queue("Applied Via", job.applied_via)
            if job.priority:
                queue("Priority", job.priority)
            if job.stage_history:
                queue("Stage History", json.dumps(job.stage_history))
            else:
                initial_stage_hist = [{"stage": final_status, "entered_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}]
                queue("Stage History", json.dumps(initial_stage_hist))
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
                with log_timed_action("Fetching 'Screening QA' worksheet from Google Sheets", tag="SHEETS"):
                    qa_ws = self._spreadsheet.worksheet("Screening QA")
                    records = qa_ws.get_all_records()
                self._cached_screening_qa = records
                self._screening_qa_cache_time = now
                log_sheets(f"Loaded {len(records)} screening Q&A records from Google Sheets.")
            except Exception as e:
                if "429" in str(e) or "Quota exceeded" in str(e):
                    log_warn("Google Sheets read quota reached. Serving cached screening QA if available.")
                    if self._cached_screening_qa is not None:
                        records = self._cached_screening_qa
                    else:
                        return []
                else:
                    log_sheets(f"Screening QA worksheet notice: {e}")
                    return []
        if opportunity_id:
            return [r for r in records if str(r.get("opportunity_id", "")).strip() == opportunity_id]
        return records

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
        if not self.is_connected:
            return False
        try:
            ingest_ws = self._spreadsheet.worksheet("Raw Ingestion")
            if not self._headers_cache:
                self._headers_cache = [h.strip() for h in ingest_ws.row_values(1)]
            headers = list(self._headers_cache)

            # Ensure all needed columns exist in header
            needed_cols = [
                "Stage History", "Category", "Applied Via", "Priority",
                "Employment Arrangement", "Worker Classification", "Pay Basis",
                "Contract Duration", "Contract Value", "Staffing Agency",
                "Client Company", "Extension Possible", "FTE Conversion"
            ]
            missing_cols = [col for col in needed_cols if col not in headers]
            if missing_cols:
                needed_total = len(headers) + len(missing_cols)
                if needed_total > ingest_ws.col_count:
                    ingest_ws.add_cols(needed_total - ingest_ws.col_count + 5)
                header_cells = [
                    gspread.Cell(row=1, col=len(headers) + 1 + i, value=col_name)
                    for i, col_name in enumerate(missing_cols)
                ]
                ingest_ws.update_cells(header_cells)
                headers.extend(missing_cols)
                self._headers_cache = headers

            opp_id_col = headers.index("Opportunity ID") + 1 if "Opportunity ID" in headers else 10
            status_col = headers.index("Status") + 1 if "Status" in headers else 7
            notes_col = headers.index("Notes") + 1 if "Notes" in headers else None
            stage_hist_col = headers.index("Stage History") + 1 if "Stage History" in headers else None
            cat_col = headers.index("Category") + 1 if "Category" in headers else None
            applied_via_col = headers.index("Applied Via") + 1 if "Applied Via" in headers else None
            priority_col = headers.index("Priority") + 1 if "Priority" in headers else None
            arr_col = headers.index("Employment Arrangement") + 1 if "Employment Arrangement" in headers else None
            wc_col = headers.index("Worker Classification") + 1 if "Worker Classification" in headers else None
            pb_col = headers.index("Pay Basis") + 1 if "Pay Basis" in headers else None
            cd_col = headers.index("Contract Duration") + 1 if "Contract Duration" in headers else None
            cv_col = headers.index("Contract Value") + 1 if "Contract Value" in headers else None
            sa_col = headers.index("Staffing Agency") + 1 if "Staffing Agency" in headers else None
            cc_col = headers.index("Client Company") + 1 if "Client Company" in headers else None
            ext_col = headers.index("Extension Possible") + 1 if "Extension Possible" in headers else None
            fte_col = headers.index("FTE Conversion") + 1 if "FTE Conversion" in headers else None
            comp_col = headers.index("Company Name") + 1 if "Company Name" in headers else None
            title_col = headers.index("Job Title") + 1 if "Job Title" in headers else None
            pay_col = headers.index("Target Pay Range") + 1 if "Target Pay Range" in headers else None
            url_col = headers.index("Source URL") + 1 if "Source URL" in headers else None

            # Fast row lookup by Opportunity ID column values instead of downloading entire sheet
            id_column_values = ingest_ws.col_values(opp_id_col)
            target_row = None
            for r_idx, val in enumerate(id_column_values[1:], start=2):
                if str(val).strip() == opportunity_id:
                    target_row = r_idx
                    break

            if target_row:
                idx = target_row
                print(f"INFO: Updating opportunity '{opportunity_id}' in Google Sheets (Row {idx})...", flush=True)
                cell_updates = [gspread.Cell(row=idx, col=status_col, value=status)]
                if company_name is not None and comp_col:
                    cell_updates.append(gspread.Cell(row=idx, col=comp_col, value=company_name))
                if job_title is not None and title_col:
                    cell_updates.append(gspread.Cell(row=idx, col=title_col, value=job_title))
                if target_pay_range is not None and pay_col:
                    cell_updates.append(gspread.Cell(row=idx, col=pay_col, value=target_pay_range))
                if source_url is not None and url_col:
                    cell_updates.append(gspread.Cell(row=idx, col=url_col, value=source_url))
                if notes is not None and notes_col:
                    cell_updates.append(gspread.Cell(row=idx, col=notes_col, value=notes))
                if stage_history is not None and stage_hist_col:
                    cell_updates.append(gspread.Cell(row=idx, col=stage_hist_col, value=json.dumps(stage_history)))
                if category is not None and cat_col:
                    cell_updates.append(gspread.Cell(row=idx, col=cat_col, value=category))
                if applied_via is not None and applied_via_col:
                    cell_updates.append(gspread.Cell(row=idx, col=applied_via_col, value=applied_via))
                if priority is not None and priority_col:
                    cell_updates.append(gspread.Cell(row=idx, col=priority_col, value=priority))
                if employment_arrangement is not None and arr_col:
                    cell_updates.append(gspread.Cell(row=idx, col=arr_col, value=employment_arrangement))
                if worker_classification is not None and wc_col:
                    cell_updates.append(gspread.Cell(row=idx, col=wc_col, value=worker_classification))
                if pay_basis is not None and pb_col:
                    cell_updates.append(gspread.Cell(row=idx, col=pb_col, value=pay_basis))
                if contract_length_raw is not None and cd_col:
                    cell_updates.append(gspread.Cell(row=idx, col=cd_col, value=contract_length_raw))
                if contract_value_display is not None and cv_col:
                    cell_updates.append(gspread.Cell(row=idx, col=cv_col, value=contract_value_display))
                if staffing_agency is not None and sa_col:
                    cell_updates.append(gspread.Cell(row=idx, col=sa_col, value=staffing_agency))
                if client_company is not None and cc_col:
                    cell_updates.append(gspread.Cell(row=idx, col=cc_col, value=client_company))
                if extension_possible is not None and ext_col:
                    cell_updates.append(gspread.Cell(row=idx, col=ext_col, value="Yes" if extension_possible else "No"))
                if fte_conversion_possible is not None and fte_col:
                    cell_updates.append(gspread.Cell(row=idx, col=fte_col, value="Yes" if fte_conversion_possible else "No"))

                ingest_ws.update_cells(cell_updates)
                if self._cached_opportunities is not None:
                    for item in self._cached_opportunities:
                        if str(item.get("Opportunity ID", "")).strip() == opportunity_id:
                            item["Status"] = status
                            if company_name is not None:
                                item["Company Name"] = company_name
                            if job_title is not None:
                                item["Job Title"] = job_title
                            if target_pay_range is not None:
                                item["Target Pay Range"] = target_pay_range
                            if source_url is not None:
                                item["Source URL"] = source_url
                            if notes is not None:
                                item["Notes"] = notes
                            if stage_history is not None:
                                item["Stage History"] = stage_history
                                item["stage_history"] = stage_history
                            if category is not None:
                                item["Category"] = category
                            if applied_via is not None:
                                item["Applied Via"] = applied_via
                                item["applied_via"] = applied_via
                            if priority is not None:
                                item["Priority"] = priority
                                item["priority"] = priority
                            if employment_arrangement is not None:
                                item["Employment Arrangement"] = employment_arrangement
                            if worker_classification is not None:
                                item["Worker Classification"] = worker_classification
                            if pay_basis is not None:
                                item["Pay Basis"] = pay_basis
                            if contract_length_raw is not None:
                                item["Contract Duration"] = contract_length_raw
                            if contract_value_display is not None:
                                item["Contract Value"] = contract_value_display
                            if staffing_agency is not None:
                                item["Staffing Agency"] = staffing_agency
                            if client_company is not None:
                                item["Client Company"] = client_company
                            if extension_possible is not None:
                                item["Extension Possible"] = "Yes" if extension_possible else "No"
                            if fte_conversion_possible is not None:
                                item["FTE Conversion"] = "Yes" if fte_conversion_possible else "No"
                            break
                    self._opportunities_cache_time = time.time()
                print(f"INFO: Successfully updated opportunity '{opportunity_id}' in Google Sheets.", flush=True)
                return True
            print(f"WARNING: Opportunity ID '{opportunity_id}' not found in Google Sheets rows.", flush=True)
            return False
        except Exception as e:
            print(f"ERROR: Failed to update status in Google Sheets: {e}", flush=True)
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
            with log_timed_action("Fetching live pipeline opportunities from 'Raw Ingestion'", tag="SHEETS"):
                worksheet = self._spreadsheet.worksheet("Raw Ingestion")
                records = worksheet.get_all_records()
            for r in records:
                sh = r.get("Stage History")
                parsed_sh = []
                if isinstance(sh, list):
                    parsed_sh = sh
                elif isinstance(sh, str) and sh.strip():
                    try:
                        parsed_sh = json.loads(sh)
                        if not isinstance(parsed_sh, list):
                            parsed_sh = []
                    except Exception:
                        parsed_sh = []
                r["stage_history"] = parsed_sh
                r["Stage History"] = parsed_sh
            self._cached_opportunities = records
            self._opportunities_cache_time = now
            log_sheets(f"Loaded {len(records)} opportunities from Google Sheets.")
            return records
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                log_warn("Google Sheets read quota reached. Serving cached opportunities.")
                if self._cached_opportunities is not None:
                    return self._cached_opportunities
            log_error(f"Failed to fetch opportunities from Google Sheets: {e}")
            return self._cached_opportunities or []
