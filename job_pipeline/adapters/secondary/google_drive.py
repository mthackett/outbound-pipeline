import io
import os
import re
import json
import uuid
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload, MediaInMemoryUpload

from job_pipeline.domain.models import ScreeningQA
from job_pipeline.domain.services import ScreeningQAService, IngestionRecoveryService
from job_pipeline.ports.storage_port import DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.adapters.secondary.resume_selector import TitleBasedResumeSelector
from job_pipeline.adapters.secondary.google_auth import SCOPES
from job_pipeline.logger import log_drive, log_warn, log_timed_action


class GoogleDriveAdapter(DocumentStoragePort, ResumeRepositoryPort):
    """Secondary Driven Adapter for Google Drive & Google Docs operations."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        resumes_folder_id: Optional[str] = None,
        root_applications_folder_id: Optional[str] = None
    ):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
        self.resumes_folder_id = resumes_folder_id or os.environ.get("GOOGLE_RESUMES_FOLDER_ID", "")
        self.root_applications_folder_id = root_applications_folder_id or os.environ.get("GOOGLE_APPLICATIONS_ROOT_FOLDER_ID")
        self._drive_svc = None
        self._docs_svc = None
        self._router = TitleBasedResumeSelector()
        self._init_services()

    def _init_services(self):
        from job_pipeline.adapters.secondary.google_auth import get_google_auth_context
        self.auth_context = get_google_auth_context(credentials_path=self.credentials_path)
        self.auth_type = self.auth_context.mode
        creds = self.auth_context.credentials

        if creds is None:
            log_warn(f"No valid Google credentials found (checked OAuth token.json and '{self.credentials_path}'). Google Drive adapter disabled.")
            return

        try:
            with log_timed_action("Initializing Google Drive v3 & Docs v1 API services", tag="DRIVE"):
                self._drive_svc = build("drive", "v3", credentials=creds)
                self._docs_svc = build("docs", "v1", credentials=creds)
            log_drive(f"Google Drive Adapter connected (Auth Mode: {self.auth_type}).")
        except Exception as e:
            log_warn(f"Could not initialize Google Drive API: {e}")

    @property
    def is_connected(self) -> bool:
        return self._drive_svc is not None

    # --- DocumentStoragePort Implementation ---

    def _share_with_configured_recipient(self, file_id: str) -> None:
        """Only explicit user sharing; never grant anonymous access as a fallback."""
        recipient = (os.environ.get("CANDIDATE_EMAIL") or os.environ.get("GOOGLE_USER_EMAIL") or "").strip()
        if recipient:
            try:
                self._drive_svc.permissions().create(
                    fileId=file_id,
                    body={"type": "user", "role": "writer", "emailAddress": recipient}
                ).execute()
            except Exception as exc:
                log_warn(f"Explicit Drive sharing failed: {exc}")

    def _list_files(self, query: str, fields: str) -> List[Dict[str, Any]]:
        """A failed provider read must not be mistaken for an empty directory."""
        if not self.is_connected:
            raise RuntimeError("Google Drive is unavailable; workspace state could not be verified.")
        files = []
        token = None
        while True:
            args = {"q": query, "fields": f"nextPageToken, files({fields})", "pageSize": 100}
            if token:
                args["pageToken"] = token
            result = self._drive_svc.files().list(**args).execute()
            files.extend(result.get("files", []))
            token = result.get("nextPageToken")
            if not token:
                return files

    def ensure_workspace_opportunity_id(self, folder_id: str, opportunity_id: Optional[str] = None) -> str:
        if not self.is_connected:
            raise RuntimeError("Google Drive is unavailable; cannot preserve ingestion identity.")
        folder = self._drive_svc.files().get(
            fileId=folder_id, fields="id, mimeType, parents, trashed, properties"
        ).execute()
        if folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder":
            raise ValueError("Recovery target is not an active workspace folder.")
        if self.root_applications_folder_id and self.root_applications_folder_id not in folder.get("parents", []):
            raise ValueError("Workspace is outside the configured application parent.")
        props = folder.get("properties") or {}
        existing = props.get("opportunity_id")
        if existing and opportunity_id and existing != opportunity_id:
            raise ValueError("Workspace and canonical opportunity identities conflict; manual review is required.")
        if existing:
            return existing
        # Legacy folders get a stable ID even if an update response is lost.
        resolved = opportunity_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"more-outbound:drive:{folder_id}"))
        self._drive_svc.files().update(
            fileId=folder_id, body={"properties": {"opportunity_id": resolved}}, fields="id"
        ).execute()
        return resolved

    def save_ingestion_checkpoint(self, folder_id: str, payload: Dict[str, Any]) -> bool:
        try:
            existing = [f for f in self.list_workspace_files(folder_id) if f.get("name") == "ingestion_input.json"]
            if len(existing) > 1:
                raise ValueError("Multiple ingestion checkpoints require manual review.")
            media = MediaInMemoryUpload(json.dumps(payload).encode("utf-8"), mimetype="application/json")
            if existing:
                self._drive_svc.files().update(fileId=existing[0]["id"], media_body=media, fields="id").execute()
            else:
                self._drive_svc.files().create(
                    body={"name": "ingestion_input.json", "mimeType": "application/json", "parents": [folder_id]},
                    media_body=media, fields="id"
                ).execute()
            return True
        except Exception as exc:
            log_warn(f"Could not persist ingestion checkpoint: {exc}")
            return False

    def fetch_ingestion_checkpoint(self, folder_id: str) -> Dict[str, Any]:
        files = [f for f in self.list_workspace_files(folder_id) if f.get("name") == "ingestion_input.json"]
        if not files:
            folder = self._drive_svc.files().get(fileId=folder_id, fields="properties").execute()
            if (folder.get("properties") or {}).get("managed_by") == "more-outbound":
                raise RuntimeError("The workspace intake checkpoint is missing. Retry the original intake to preserve its answers and choices.")
            return {}
        if len(files) != 1:
            raise ValueError("Multiple ingestion checkpoints require manual review.")
        content = self._drive_svc.files().get_media(fileId=files[0]["id"]).execute()
        payload = json.loads(content)
        if not isinstance(payload, dict) or not payload.get("opportunity_id"):
            raise ValueError("Workspace ingestion checkpoint is invalid; retry after restoring it.")
        return payload

    def create_application_workspace(self, company_name: str, job_title: str, opportunity_id: Optional[str] = None) -> Dict[str, str]:
        if not self.is_connected:
            raise RuntimeError("Google Drive is unavailable; cannot create a recoverable workspace.")

        opportunity_id = opportunity_id or str(uuid.uuid4())
        escaped_id = opportunity_id.replace("\\", "\\\\").replace("'", "\\'")
        query = ("mimeType = 'application/vnd.google-apps.folder' and trashed = false "
                 f"and properties has {{ key='opportunity_id' and value='{escaped_id}' }}")
        if self.root_applications_folder_id:
            query += f" and '{self.root_applications_folder_id}' in parents"
        existing = self._list_files(query, "id, webViewLink, properties")
        if len(existing) > 1:
            raise RuntimeError("Multiple workspaces have this opportunity ID; manual review is required.")
        if existing:
            folder = existing[0]
            return {"folder_id": folder["id"], "folder_link": folder.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder['id']}", "opportunity_id": opportunity_id}

        from datetime import datetime
        safe_company = "".join([c for c in company_name if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_")
        safe_title = "".join([c for c in job_title if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_")
        app_date = datetime.now().strftime("%Y-%m-%d")
        folder_name = f"{safe_company}_{safe_title}_{app_date}"

        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "properties": {
                "managed_by": "more-outbound",
                "opportunity_id": opportunity_id,
                "ingestion_status": "incomplete",
                "company": company_name,
                "title": job_title
            }
        }
        if self.root_applications_folder_id:
            file_metadata["parents"] = [self.root_applications_folder_id]

        try:
            folder = self._drive_svc.files().create(
                body=file_metadata,
                fields="id, webViewLink"
            ).execute()
            folder_id = folder.get("id")
            folder_link = folder.get("webViewLink")

            self._share_with_configured_recipient(folder_id)

            # Create a shortcut to the master pipeline spreadsheet inside the application folder
            sheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
            if sheet_id:
                try:
                    self._drive_svc.files().create(
                        body={
                            "name": "Pipeline Tracker (Master Sheet)",
                            "mimeType": "application/vnd.google-apps.shortcut",
                            "parents": [folder_id],
                            "shortcutDetails": {"targetId": sheet_id}
                        },
                        fields="id, webViewLink"
                    ).execute()
                    print("SUCCESS: Created master sheet shortcut in application folder.")
                except Exception as sc_err:
                    print(f"INFO: Sheet shortcut notice: {sc_err}")

            return {"folder_id": folder_id, "folder_link": folder_link or f"https://drive.google.com/drive/folders/{folder_id}", "opportunity_id": opportunity_id}
        except Exception as e:
            print(f"ERROR: Failed to create Drive application folder: {e}")
            return {"folder_id": "", "folder_link": ""}

    def upload_raw_job_description(self, folder_id: str, raw_text: str, company_name: str = "", job_title: str = "") -> Optional[Dict[str, str]]:
        """Creates a Google Doc with raw JD text inside the application folder (0 quota bytes)."""
        # Save local backup on disk
        os.makedirs("output_reports", exist_ok=True)
        if company_name or job_title:
            safe_c = re.sub(r'[^a-zA-Z0-9]', '_', company_name)
            safe_t = re.sub(r'[^a-zA-Z0-9]', '_', job_title)
            try:
                with open(f"output_reports/{safe_c}_{safe_t}_Raw_Job_Description.txt", "w", encoding="utf-8") as f:
                    f.write(raw_text)
            except Exception as io_err:
                print(f"INFO: Local disk backup notice: {io_err}")

        if not self.is_connected or not folder_id or folder_id == "mock_folder_id":
            return None

        if hasattr(self, "auth_context") and self.auth_context and not self.auth_context.can_create_drive_files:
            log_warn(f"[AUTH] Operation 'upload_raw_job_description' requires user OAuth credentials. Operating in '{self.auth_context.mode}' mode; skipping Google Doc upload. Local disk backup preserved.")
            return None

        file_metadata = {
            "name": "Raw Job Description",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }
        media = MediaInMemoryUpload(raw_text.encode("utf-8"), mimetype="text/plain", resumable=False)

        try:
            existing = self._list_files(
                f"'{folder_id}' in parents and name = 'Raw Job Description' and trashed = false",
                "id, webViewLink",
            )
            if len(existing) > 1:
                raise ValueError("Multiple raw JD documents require manual reconciliation.")
            if existing:
                doc_id = existing[0]["id"]
                existing_text = re.sub(r'\s+', ' ', (self.fetch_resume_text(doc_id) or "").lstrip("\ufeff")).strip()
                incoming_text = re.sub(r'\s+', ' ', (raw_text or "").lstrip("\ufeff")).strip()
                if existing_text != incoming_text:
                    raise ValueError("This workspace already holds a different job description. Resume it or start a new intake.")
                return {"file_id": doc_id, "file_link": existing[0].get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"}
            doc_file = self._drive_svc.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink"
            ).execute()
            doc_id = doc_file.get("id")
            doc_link = doc_file.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"

            self._share_with_configured_recipient(doc_id)

            return {"file_id": doc_id, "file_link": doc_link}
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                print("INFO: Service Account storage quota notice. Ensure your Google Drive root applications folder is shared with your service account email as Editor.")
            else:
                print(f"ERROR: Failed to create Raw Job Description Google Doc: {e}")
            return None

    def create_screening_questions_doc(
        self,
        folder_id: str,
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        opportunity_id: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Creates a Google Doc titled 'Screening Questions' inside the application folder."""
        formatted_text = ScreeningQAService.format_screening_gdoc_text(
            company_name=company_name,
            job_title=job_title,
            qa_items=qa_items,
            opportunity_id=opportunity_id
        )

        os.makedirs("output_reports", exist_ok=True)
        safe_c = re.sub(r'[^a-zA-Z0-9]', '_', company_name)
        safe_t = re.sub(r'[^a-zA-Z0-9]', '_', job_title)
        try:
            with open(f"output_reports/{safe_c}_{safe_t}_Screening_Questions.txt", "w", encoding="utf-8") as f:
                f.write(formatted_text)
        except Exception as io_err:
            print(f"INFO: Local screening backup notice: {io_err}")

        if not self.is_connected or not folder_id or folder_id == "mock_folder_id":
            return None

        if hasattr(self, "auth_context") and self.auth_context and not self.auth_context.can_create_drive_files:
            log_warn(f"[AUTH] Operation 'create_screening_questions_doc' requires user OAuth credentials. Operating in '{self.auth_context.mode}' mode; skipping Google Doc creation. Local disk backup preserved.")
            return None

        file_metadata = {
            "name": "Screening Questions",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }
        media = MediaInMemoryUpload(formatted_text.encode("utf-8"), mimetype="text/plain", resumable=False)

        try:
            # Check if a 'Screening Questions' doc already exists in this folder
            existing_query = f"'{folder_id}' in parents and name = 'Screening Questions' and trashed = false"
            existing_files = self._drive_svc.files().list(
                q=existing_query,
                fields="files(id, webViewLink)",
                pageSize=1
            ).execute().get("files", [])

            if existing_files:
                doc_id = existing_files[0]["id"]
                doc_link = existing_files[0].get("webViewLink")
                updated_file = self._drive_svc.files().update(
                    fileId=doc_id,
                    media_body=media,
                    fields="id, webViewLink"
                ).execute()
                doc_link = updated_file.get("webViewLink", doc_link)
                print(f"SUCCESS: Updated existing Screening Questions Google Doc: {doc_id}")
                return {"file_id": doc_id, "file_link": doc_link}

            doc_file = self._drive_svc.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink"
            ).execute()
            doc_id = doc_file.get("id")
            doc_link = doc_file.get("webViewLink")

            self._share_with_configured_recipient(doc_id)

            return {"file_id": doc_id, "file_link": doc_link}
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                print("INFO: Service Account storage quota notice for Screening Questions doc. (Authenticate with personal OAuth 2.0 via `python -m job_pipeline.setup_oauth` to create native Google Docs).")
            else:
                print(f"ERROR: Failed to create Screening Questions Google Doc: {e}")
            return None

    def export_resume_pdf(self, resume_doc_id: str, folder_id: str, output_filename: str) -> Optional[str]:
        """Creates a Google Doc copy of the candidate resume inside the application folder (0 quota bytes)."""
        if not self.is_connected or not resume_doc_id or not folder_id or folder_id == "mock_folder_id":
            return None

        if resume_doc_id.startswith("doc_") or resume_doc_id.startswith("res-"):
            return None

        try:
            copy_metadata = {
                "name": output_filename.replace(".pdf", ""),
                "parents": [folder_id]
            }
            copied_file = self._drive_svc.files().copy(
                fileId=resume_doc_id,
                body=copy_metadata,
                fields="id, webViewLink"
            ).execute()
            return copied_file.get("id")
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                # Service account has 0 quota in personal Google Drive -> create a native Shortcut to the resume instead!
                try:
                    sc = self._drive_svc.files().create(
                        body={
                            "name": output_filename.replace(".pdf", ""),
                            "mimeType": "application/vnd.google-apps.shortcut",
                            "parents": [folder_id],
                            "shortcutDetails": {"targetId": resume_doc_id}
                        },
                        fields="id, webViewLink"
                    ).execute()
                    print(f"SUCCESS: Created resume shortcut in application folder: {sc.get('id')}")
                    return sc.get("id")
                except Exception as sc_err:
                    print(f"INFO: Resume shortcut creation notice: {sc_err}")
            else:
                print(f"ERROR: Failed to copy resume Google Doc inside Drive folder: {e}")
            return None

    def upload_role_intelligence_report(self, folder_id: str, local_docx_path: str) -> Optional[str]:
        """Uploads Role Intelligence Report as a Google Doc inside the application folder (0 quota bytes)."""
        if not self.is_connected or not folder_id or folder_id == "mock_folder_id" or not os.path.exists(local_docx_path):
            return None

        if hasattr(self, "auth_context") and self.auth_context and not self.auth_context.can_create_drive_files:
            log_warn(f"[AUTH] Operation 'upload_role_intelligence_report' requires user OAuth credentials. Operating in '{self.auth_context.mode}' mode; skipping Drive upload.")
            return None
        file_metadata = {
            "name": os.path.basename(local_docx_path).replace(".docx", ""),
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }
        media = MediaFileUpload(
            local_docx_path,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        try:
            res = self._drive_svc.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink"
            ).execute()
            return res.get("id")
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                print(f"INFO: Service Account storage quota notice for DOCX upload.")
            else:
                print(f"ERROR: Failed to upload Role Intelligence Report Google Doc to Drive: {e}")
            return None

    def mark_workspace_complete(self, folder_id: str) -> bool:
        """Marks a workspace as successfully completed in Google Drive properties."""
        if not self.is_connected or not folder_id or folder_id == "mock_folder_id":
            return False
        try:
            self._drive_svc.files().update(
                fileId=folder_id,
                body={"properties": {"ingestion_status": "complete"}},
                fields="id, properties"
            ).execute()
            log_drive(f"Marked workspace folder '{folder_id}' as complete.")
            return True
        except Exception as e:
            log_warn(f"Failed to mark workspace folder '{folder_id}' complete: {e}")
            return False

    def list_workspace_files(self, folder_id: str) -> List[Dict[str, Any]]:
        if not folder_id:
            raise ValueError("Workspace ID is required.")
        return self._list_files(
            f"'{folder_id}' in parents and trashed = false",
            "id, name, mimeType, webViewLink, shortcutDetails"
        )

    def fetch_raw_job_description(self, folder_id: str) -> Optional[str]:
        """Only the source document in this exact workspace is a recovery source."""
        try:
            files = [f for f in self.list_workspace_files(folder_id)
                     if f.get("name") == "Raw Job Description"
                     and f.get("mimeType") == "application/vnd.google-apps.document"]
            if len(files) != 1:
                raise ValueError("Expected one Raw Job Description document in this workspace.")
            text = self.fetch_resume_text(files[0]["id"])
            if not text or len(text.strip()) < 20:
                raise ValueError("Workspace job description is empty or incomplete.")
            return text
        except Exception as exc:
            raise RuntimeError(
                "Cannot resume: this workspace's raw job description could not be read. "
                "Restore its Raw Job Description document and retry; the workspace remains incomplete."
            ) from exc

    def fetch_incomplete_workspaces(self, completed_folder_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Detects incomplete application workspaces in Google Drive root applications folder.
        Treats every folder as incomplete until marked complete or logged to canonical storage.
        """
        if not self.is_connected or not self.root_applications_folder_id:
            return []

        completed_set = set()
        for item in (completed_folder_ids or []):
            if not item:
                continue
            item_str = str(item)
            completed_set.add(item_str)
            m = re.search(r'[-\w]{25,}', item_str)
            if m:
                completed_set.add(m.group(0))

        query = f"'{self.root_applications_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = self._list_files(query, "id, name, webViewLink, createdTime, properties")

        incomplete_list = []
        for folder in folders:
            f_id = folder.get("id")
            props = folder.get("properties") or {}
            status = props.get("ingestion_status")

            # Explicitly incomplete folders remain recoverable even after a partial
            # Sheets write. Discovery never promotes a folder to complete.
            if status == "complete":
                continue
            if status != "incomplete" and f_id in completed_set:
                continue

            folder_name = folder.get("name", "")
            source_error = None
            try:
                raw_text = self.fetch_raw_job_description(f_id) or ""
            except RuntimeError as exc:
                raw_text = ""
                source_error = str(exc)

            # Resolve company and title
            company = props.get("company")
            title = props.get("title")
            if not company or not title or company == "Target Company" or title == "Target Role":
                parsed_c, parsed_t = IngestionRecoveryService.parse_job_identity(raw_text, folder_name)
                if parsed_c and parsed_c != "Target Company":
                    company = parsed_c
                    title = parsed_t
                else:
                    company = company or parsed_c
                    title = title or parsed_t

            preview = IngestionRecoveryService.extract_jd_preview(raw_text)
            date_display = IngestionRecoveryService.format_created_date(folder.get("createdTime"))
            existing_files = self.list_workspace_files(f_id)

            incomplete_list.append({
                "folder_id": f_id,
                "folder_link": folder.get("webViewLink", f"https://drive.google.com/drive/folders/{f_id}"),
                "folder_name": folder_name,
                "company": company or "Unknown Company",
                "title": title or "Unknown Role",
                "created_time": folder.get("createdTime"),
                "created_date_display": date_display,
                "raw_jd_text": raw_text,
                "source_error": source_error,
                "opportunity_id": props.get("opportunity_id"),
                "raw_jd_preview": preview,
                "existing_files": existing_files
            })

        return incomplete_list

    def delete_application_workspace(self, folder_id: str, canonical_opportunities: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Conservative reversible cleanup. Caller must supply a fresh verified snapshot."""
        if not self.is_connected or not folder_id or canonical_opportunities is None:
            return False
        try:
            folder = self._drive_svc.files().get(
                fileId=folder_id, fields="id, mimeType, parents, ownedByMe, trashed, properties"
            ).execute()
            props = folder.get("properties") or {}
            if (folder.get("mimeType") != "application/vnd.google-apps.folder"
                    or not folder.get("ownedByMe")
                    or props.get("managed_by") != "more-outbound"
                    or props.get("ingestion_status") != "incomplete"
                    or not props.get("opportunity_id")):
                raise ValueError("Workspace ownership or incomplete state cannot be verified; review it manually in Drive.")
            if self.root_applications_folder_id and self.root_applications_folder_id not in folder.get("parents", []):
                raise ValueError("Workspace is outside the configured application parent.")
            for record in canonical_opportunities:
                link = str(record.get("Drive Folder Link") or "")
                match = re.search(r"(?:folders/|[?&]id=)([\w-]+)", link)
                if ((match and match.group(1) == folder_id) or link == folder_id
                        or str(record.get("Opportunity ID", "")).strip() == props["opportunity_id"]):
                    raise ValueError("Workspace has a canonical opportunity; discard is not allowed.")
            if not folder.get("trashed"):
                self._drive_svc.files().update(fileId=folder_id, body={"trashed": True}, fields="id, trashed").execute()
            log_drive(f"Moved incomplete workspace to Drive trash: {folder_id}")
            return True
        except Exception as exc:
            log_warn(f"Workspace was not discarded: {exc}")
            return False

    def rename_application_workspace(self, folder_id: str, new_name: str) -> bool:
        """Renames an existing Drive application workspace folder."""
        if not self.is_connected or not folder_id or folder_id == "mock_folder_id":
            return True
        try:
            self._drive_svc.files().update(
                fileId=folder_id,
                body={"name": new_name},
                fields="id, name"
            ).execute()
            log_drive(f"Renamed Drive workspace '{folder_id}' to '{new_name}'.")
            return True
        except Exception as e:
            log_warn(f"Failed to rename Drive workspace folder '{folder_id}': {e}")
            return False

    # --- ResumeRepositoryPort Implementation ---

    def list_available_resumes(self) -> List[ResumeFileRef]:
        if not self.is_connected or not self.resumes_folder_id:
            raise RuntimeError("Google resume storage is unavailable or not configured.")

        query = f"'{self.resumes_folder_id}' in parents and mimeType = 'application/vnd.google-apps.document' and trashed = false"
        try:
            results = self._drive_svc.files().list(q=query, pageSize=50, fields="files(id, name, webViewLink)").execute()
            files = results.get("files", [])
            resumes = []
            for f in files:
                f_id = f.get("id")
                clean_label = re.sub(r'(?i)\b(resume|cv|doc)\b', '', f.get("name", "")).strip()
                link = f.get("webViewLink") or f"https://docs.google.com/document/d/{f_id}/edit"
                resumes.append(ResumeFileRef(
                    doc_id=f_id,
                    filename=f.get("name"),
                    role_label=clean_label,
                    web_link=link
                ))
            return resumes
        except Exception as e:
            print(f"ERROR: Failed to list resumes from Google Drive: {e}")
            return []

    def fetch_resume_text(self, doc_id: str) -> str:
        if not self.is_connected or not doc_id:
            raise RuntimeError("Google document text is unavailable; no sample content will be substituted.")

        try:
            request = self._drive_svc.files().export_media(fileId=doc_id, mimeType="text/plain")
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return fh.getvalue().decode("utf-8-sig", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
        except Exception as e:
            print(f"WARNING: Drive export failed for doc '{doc_id}': {e}. Falling back to Docs API...")

        if self._docs_svc:
            try:
                document = self._docs_svc.documents().get(documentId=doc_id).execute()
                text_runs = []
                for element in document.get("body", {}).get("content", []):
                    paragraph = element.get("paragraph")
                    if paragraph:
                        for elem in paragraph.get("elements", []):
                            text_run = elem.get("textRun")
                            if text_run and text_run.get("content"):
                                text_runs.append(text_run.get("content"))
                return "".join(text_runs)
            except Exception as e:
                print(f"ERROR: Docs API text extraction failed for doc '{doc_id}': {e}")

        raise RuntimeError(f"Could not read Google document {doc_id}; restore access and retry.")

    def select_best_fit_resume(self, job_title: str, title_family: str) -> Optional[ResumeFileRef]:
        available = self.list_available_resumes()
        drive_file_dicts = [{"id": r.doc_id, "name": r.filename} for r in available]
        match_result = self._router.select_resume(job_title, title_family, drive_file_dicts)

        if match_result.selected_resume:
            for r in available:
                if r.doc_id == match_result.selected_resume.doc_id:
                    return r
        return available[0] if available else None
