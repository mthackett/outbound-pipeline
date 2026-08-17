import io
import os
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload, MediaInMemoryUpload
from oauth2client.service_account import ServiceAccountCredentials

from job_pipeline.ports.storage_port import DocumentStoragePort
from job_pipeline.ports.resume_port import ResumeRepositoryPort, ResumeFileRef
from job_pipeline.adapters.secondary.resume_selector import TitleBasedResumeSelector


SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly"
]


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
        if not os.path.exists(self.credentials_path):
            print(f"WARNING: Credentials file '{self.credentials_path}' not found. Google Drive adapter disabled.")
            return

        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, SCOPES)
            self._drive_svc = build("drive", "v3", credentials=creds)
            self._docs_svc = build("docs", "v1", credentials=creds)
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
                print(f"INFO: Drive permission notice: {perm_err}")

            return {"folder_id": folder_id, "folder_link": folder_link}
        except Exception as e:
            print(f"ERROR: Failed to create Drive application folder: {e}")
            return {"folder_id": "", "folder_link": ""}

    def upload_raw_job_description(self, folder_id: str, raw_text: str) -> Optional[Dict[str, str]]:
        """Creates a Google Doc with raw JD text inside the application folder (0 quota bytes)."""
        if not self.is_connected or not folder_id or folder_id == "mock_folder_id":
            return {"file_id": "mock_file_id", "file_link": "https://drive.google.com/mock_file"}

        file_metadata = {
            "name": "Raw Job Description",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }

        try:
            doc_file = self._drive_svc.files().create(
                body=file_metadata,
                fields="id, webViewLink"
            ).execute()
            doc_id = doc_file.get("id")
            doc_link = doc_file.get("webViewLink")

            # Write text content to Google Doc using Docs API
            if self._docs_svc and doc_id:
                try:
                    self._docs_svc.documents().batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "insertText": {
                                        "location": {"index": 1},
                                        "text": raw_text
                                    }
                                }
                            ]
                        }
                    ).execute()
                except Exception as doc_err:
                    print(f"INFO: Text insert into Google Doc notice: {doc_err}")

            return {"file_id": doc_id, "file_link": doc_link}
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                print(f"INFO: Service Account storage quota notice. Share folder 'your-google-drive-applications-root-folder-id-here' with service account email 'your-service-account@your-project.iam.gserviceaccount.com' as Editor.")
            else:
                print(f"ERROR: Failed to create Raw Job Description Google Doc: {e}")
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
                print(f"INFO: Service Account storage quota notice for resume copy.")
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
            results = self._drive_svc.files().list(q=query, pageSize=50, fields="files(id, name)").execute()
            files = results.get("files", [])
            resumes = []
            for f in files:
                clean_label = re.sub(r'(?i)\b(resume|cv|doc)\b', '', f.get("name", "")).strip()
                resumes.append(ResumeFileRef(doc_id=f.get("id"), filename=f.get("name"), role_label=clean_label))
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
