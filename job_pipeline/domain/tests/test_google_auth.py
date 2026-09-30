import os
import unittest
from unittest.mock import patch, MagicMock

from job_pipeline.adapters.secondary.google_auth import (
    GoogleAuthContext,
    get_google_auth_context,
    get_google_credentials
)
from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter


class TestGoogleAuthContextAndCapabilities(unittest.TestCase):

    def test_auth_context_properties_oauth(self):
        ctx = GoogleAuthContext(mode="oauth", credentials=MagicMock())
        self.assertTrue(ctx.can_create_drive_files)
        self.assertTrue(ctx.can_access_configured_sheet)
        self.assertTrue(ctx.can_read_drive)
        self.assertIsNone(ctx.warning_message)

    def test_auth_context_properties_service_account_fallback(self):
        ctx = GoogleAuthContext(
            mode="service_account",
            credentials=MagicMock(),
            oauth_failed=True,
            is_revoked=True,
            oauth_error="invalid_grant: Token has been expired or revoked."
        )
        self.assertFalse(ctx.can_create_drive_files)
        self.assertTrue(ctx.can_access_configured_sheet)
        self.assertTrue(ctx.can_read_drive)
        self.assertIsNotNone(ctx.warning_message)
        self.assertIn("Service Account fallback mode", ctx.warning_message)
        self.assertIn("OAuth token expired or revoked", ctx.warning_message)
        self.assertIn("python -m job_pipeline.setup_oauth", ctx.reauth_instruction)

    def test_auth_context_properties_unavailable(self):
        ctx = GoogleAuthContext(mode="unavailable", credentials=None)
        self.assertFalse(ctx.can_create_drive_files)
        self.assertFalse(ctx.can_access_configured_sheet)
        self.assertFalse(ctx.can_read_drive)
        self.assertIsNotNone(ctx.warning_message)

    @patch("job_pipeline.adapters.secondary.google_auth.OAuthCredentials")
    @patch("os.path.exists")
    def test_valid_oauth_credentials(self, mock_exists, mock_oauth_cls):
        mock_exists.return_value = True
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True
        mock_oauth_cls.from_authorized_user_file.return_value = mock_creds

        ctx = get_google_auth_context(token_path="mock_token.json", credentials_path="mock_sa.json")
        self.assertEqual(ctx.mode, "oauth")
        self.assertTrue(ctx.can_create_drive_files)
        self.assertFalse(ctx.oauth_failed)

        creds, auth_type = get_google_credentials(token_path="mock_token.json", credentials_path="mock_sa.json")
        self.assertEqual(auth_type, "oauth_user")
        self.assertEqual(creds, mock_creds)

    @patch("builtins.open", create=True)
    @patch("job_pipeline.adapters.secondary.google_auth.OAuthCredentials")
    @patch("os.path.exists")
    def test_expired_oauth_credentials_refresh_success(self, mock_exists, mock_oauth_cls, mock_open):
        mock_exists.return_value = True
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "valid_refresh_token"
        # Calling refresh makes it valid
        def do_refresh(request):
            mock_creds.expired = False
            mock_creds.valid = True
        mock_creds.refresh.side_effect = do_refresh
        mock_creds.to_json.return_value = '{"token": "refreshed"}'
        mock_oauth_cls.from_authorized_user_file.return_value = mock_creds

        ctx = get_google_auth_context(token_path="mock_token.json", credentials_path="mock_sa.json")
        self.assertEqual(ctx.mode, "oauth")
        self.assertTrue(ctx.can_create_drive_files)
        self.assertFalse(ctx.oauth_failed)
        mock_creds.refresh.assert_called_once()

    @patch("job_pipeline.adapters.secondary.google_auth.ServiceAccountCredentials")
    @patch("job_pipeline.adapters.secondary.google_auth.OAuthCredentials")
    @patch("os.path.exists")
    def test_revoked_oauth_invalid_grant_falls_back_to_service_account(self, mock_exists, mock_oauth_cls, mock_sa_cls):
        mock_exists.return_value = True
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "bad_refresh_token"
        mock_creds.refresh.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
        mock_oauth_cls.from_authorized_user_file.return_value = mock_creds

        mock_sa = MagicMock()
        mock_sa_cls.from_service_account_file.return_value = mock_sa

        ctx = get_google_auth_context(token_path="mock_token.json", credentials_path="mock_sa.json")
        self.assertEqual(ctx.mode, "service_account")
        self.assertTrue(ctx.oauth_failed)
        self.assertTrue(ctx.is_revoked)
        self.assertFalse(ctx.can_create_drive_files)
        self.assertTrue(ctx.can_access_configured_sheet)
        self.assertEqual(ctx.credentials, mock_sa)

    @patch("job_pipeline.adapters.secondary.google_auth.ServiceAccountCredentials")
    @patch("job_pipeline.adapters.secondary.google_auth.OAuthCredentials")
    @patch("os.path.exists")
    def test_service_account_fallback_when_oauth_missing(self, mock_exists, mock_oauth_cls, mock_sa_cls):
        # Token doesn't exist, SA does exist
        mock_exists.side_effect = lambda p: p == "mock_sa.json"
        mock_sa = MagicMock()
        mock_sa_cls.from_service_account_file.return_value = mock_sa

        ctx = get_google_auth_context(token_path="mock_token.json", credentials_path="mock_sa.json")
        self.assertEqual(ctx.mode, "service_account")
        self.assertFalse(ctx.oauth_failed)
        self.assertFalse(ctx.can_create_drive_files)
        self.assertTrue(ctx.can_access_configured_sheet)

    def test_unsupported_drive_operation_under_service_account_mode(self):
        """Service account cannot create native Google Docs in personal Drive.
        Adapter must fail gracefully without throwing API quota errors.
        """
        adapter = GoogleDriveAdapter.__new__(GoogleDriveAdapter)
        adapter.credentials_path = "mock.json"
        adapter.resumes_folder_id = ""
        adapter.root_applications_folder_id = None
        adapter._drive_svc = MagicMock()
        adapter._docs_svc = MagicMock()
        adapter.auth_context = GoogleAuthContext(mode="service_account", credentials=MagicMock())
        adapter.auth_type = "service_account"

        # 1. Raw job description doc upload should skip API call and return None
        res_raw = adapter.upload_raw_job_description(
            folder_id="real_folder_id",
            raw_text="Sample JD text",
            company_name="Acme",
            job_title="RevOps Lead"
        )
        self.assertIsNone(res_raw)
        adapter._drive_svc.files().create.assert_not_called()

        # 2. Screening questions doc creation should skip API call and return None
        res_sq = adapter.create_screening_questions_doc(
            folder_id="real_folder_id",
            company_name="Acme",
            job_title="RevOps Lead",
            qa_items=[]
        )
        self.assertIsNone(res_sq)
        adapter._drive_svc.files().create.assert_not_called()

        # 3. Role intelligence docx upload should skip API call and return None
        with patch("os.path.exists", return_value=True):
            res_ri = adapter.upload_role_intelligence_report(
                folder_id="real_folder_id",
                local_docx_path="test_report.docx"
            )
            self.assertIsNone(res_ri)
            adapter._drive_svc.files().create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
