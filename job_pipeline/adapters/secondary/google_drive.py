import io
import os
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload, MediaInMemoryUpload

from job_pipeline.domain.models import ScreeningQA
from job_pipeline.domain.services import ScreeningQAService
from job_pipeline.ports.storage_port import DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.adapters.secondary.resume_selector import TitleBasedResumeSelector
from job_pipeline.adapters.secondary.google_auth import SCOPES


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
        from job_pipeline.adapters.secondary.google_auth import get_google_credentials
        creds, auth_type = get_google_credentials(credentials_path=self.credentials_path)
        self.auth_type = auth_type

        if creds is None:
            print(f"WARNING: No valid Google credentials found (checked OAuth token.json and '{self.credentials_path}'). Google Drive adapter disabled.")
            return

        try:
            self._drive_svc = build("drive", "v3", credentials=creds)
            self._docs_svc = build("docs", "v1", credentials=creds)
            print(f"INFO: Google Drive Adapter initialized successfully (Auth Type: {self.auth_type}).")
        except Exception as e:
            print(f"WARNING: Could not initialize Google Drive API: {e}")

    @property
    def is_connected(self) -> bool:
        return self._drive_svc is not None

    # --- DocumentStoragePort Implementation ---

    def create_application_workspace(self, company_name: str, job_title: str) -> Dict[str, str]:
        if not self.is_connected:
            return {"folder_id": "mock_folder_id", "folder_link": "https://drive.google.com/mock"}

        from datetime import datetime
        safe_company = "".join([c for c in company_name if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_")
        safe_title = "".join([c for c in job_title if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_")
        app_date = datetime.now().strftime("%Y-%m-%d")
        folder_name = f"{safe_company}_{safe_title}_{app_date}"

        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
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

            # Make folder accessible so links open directly in web browser
            try:
                user_email = os.environ.get("CANDIDATE_EMAIL") or os.environ.get("GOOGLE_USER_EMAIL")
                if user_email:
                    self._drive_svc.permissions().create(
                        fileId=folder_id,
                        body={"type": "user", "role": "writer", "emailAddress": user_email}
                    ).execute()
                else:
                    self._drive_svc.permissions().create(
                        fileId=folder_id,
                        body={"type": "anyone", "role": "reader"}
                    ).execute()
            except Exception as perm_err:
                print(f"INFO: Permission setting notice: {perm_err}")

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

            return {"folder_id": folder_id, "folder_link": folder_link}
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
            return {"file_id": "mock_file_id", "file_link": "https://drive.google.com/mock_file"}

        file_metadata = {
            "name": "Raw Job Description",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }
        media = MediaInMemoryUpload(raw_text.encode("utf-8"), mimetype="text/plain", resumable=False)

        try:
            doc_file = self._drive_svc.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink"
            ).execute()
            doc_id = doc_file.get("id")
            doc_link = doc_file.get("webViewLink")

            # Ensure accessible permissions
            user_email = os.environ.get("CANDIDATE_EMAIL") or os.environ.get("GOOGLE_USER_EMAIL")
            try:
                if user_email:
                    self._drive_svc.permissions().create(
                        fileId=doc_id,
                        body={"type": "user", "role": "writer", "emailAddress": user_email}
                    ).execute()
                else:
                    self._drive_svc.permissions().create(
                        fileId=doc_id,
                        body={"type": "anyone", "role": "reader"}
                    ).execute()
            except Exception as perm_err:
                print(f"INFO: Permission setting notice: {perm_err}")

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
            return {"file_id": "mock_screening_id", "file_link": "https://docs.google.com/document/d/mock_screening_questions/edit"}

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

            # Set permissions
            user_email = os.environ.get("CANDIDATE_EMAIL") or os.environ.get("GOOGLE_USER_EMAIL")
            try:
                if user_email:
                    self._drive_svc.permissions().create(
                        fileId=doc_id,
                        body={"type": "user", "role": "writer", "emailAddress": user_email}
                    ).execute()
                else:
                    self._drive_svc.permissions().create(
                        fileId=doc_id,
                        body={"type": "anyone", "role": "reader"}
                    ).execute()
            except Exception as perm_err:
                print(f"INFO: Permission setting notice for Screening Questions doc: {perm_err}")

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
            return "mock_pdf_id"

        if resume_doc_id.startswith("doc_") or resume_doc_id.startswith("res-"):
            return "mock_pdf_id"

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

    # --- ResumeRepositoryPort Implementation ---

    def list_available_resumes(self) -> List[ResumeFileRef]:
        if not self.is_connected or not self.resumes_folder_id:
            return [
                ResumeFileRef(doc_id="doc_revops_demo", filename="Candidate RevOps Analyst Resume", role_label="Revenue Operations"),
                ResumeFileRef(doc_id="doc_gtm_demo", filename="Candidate GTM Engineer Resume", role_label="GTM Engineering"),
                ResumeFileRef(doc_id="doc_ba_demo", filename="Candidate Business Analyst Resume", role_label="Business Analytics")
            ]

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
        if not self.is_connected or not doc_id or doc_id.startswith("doc_"):
            return "Built dbt models, SQL funnel analytics, Salesforce RevOps automation, and BigQuery telemetry pipelines."

        try:
            request = self._drive_svc.files().export_media(fileId=doc_id, mimeType="text/plain")
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return fh.getvalue().decode("utf-8", errors="ignore")
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

        return "Built dbt models, SQL funnel analytics, Salesforce RevOps automation, and BigQuery telemetry pipelines."

    def select_best_fit_resume(self, job_title: str, title_family: str) -> Optional[ResumeFileRef]:
        available = self.list_available_resumes()
        drive_file_dicts = [{"id": r.doc_id, "name": r.filename} for r in available]
        match_result = self._router.select_resume(job_title, title_family, drive_file_dicts)

        if match_result.selected_resume:
            for r in available:
                if r.doc_id == match_result.selected_resume.doc_id:
                    return r
        return available[0] if available else None
