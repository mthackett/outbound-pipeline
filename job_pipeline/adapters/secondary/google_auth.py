import json
import os
from typing import List, Optional, Tuple, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

# Allow relaxed scope comparison to prevent ScopeChangedError from Google OAuth server
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

SCOPES: List[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


class GoogleAuthContext:
    """Explicit, capability-aware Google Authentication context.
    
    Distinguishes between:
    - 'oauth': Authenticated personal user credentials. Has personal Drive quota.
    - 'service_account': GCP service account. Has 0 Drive storage quota on personal accounts.
    - 'unavailable': No valid credentials resolved.
    """

    def __init__(
        self,
        mode: str,  # "oauth" | "service_account" | "unavailable"
        credentials: Optional[object] = None,
        oauth_failed: bool = False,
        oauth_error: Optional[str] = None,
        is_revoked: bool = False,
        token_path: Optional[str] = None,
        credentials_path: Optional[str] = None
    ):
        self.mode = mode
        self.credentials = credentials
        self.oauth_failed = oauth_failed
        self.oauth_error = oauth_error
        self.is_revoked = is_revoked
        self.token_path = token_path
        self.credentials_path = credentials_path

    @property
    def can_create_drive_files(self) -> bool:
        """Creating Google Docs or native files in personal Google Drive requires user OAuth."""
        return self.mode == "oauth" and self.credentials is not None

    @property
    def can_access_configured_sheet(self) -> bool:
        """Accessing configured Google Sheets is supported by both user OAuth and shared Service Account."""
        return self.mode in ("oauth", "service_account") and self.credentials is not None

    @property
    def can_read_drive(self) -> bool:
        """Reading/exporting shared files in Drive is supported by both OAuth and shared Service Account."""
        return self.mode in ("oauth", "service_account") and self.credentials is not None

    @property
    def warning_message(self) -> Optional[str]:
        """User-facing warning message if operating in reduced or degraded capability mode."""
        if self.mode == "service_account":
            if self.oauth_failed:
                revoked_clause = " (OAuth token expired or revoked)" if self.is_revoked else ""
                return (
                    f"Operating in Service Account fallback mode{revoked_clause}. "
                    "Google Sheets CRM syncing is active, but Google Drive document creation (workspaces, screening docs) "
                    "is disabled because service accounts cannot create files in personal Drive. "
                    "Re-authenticate with OAuth to restore full capabilities."
                )
            return (
                "Operating in Service Account mode. "
                "Google Drive document creation is disabled. "
                "Re-authenticate with personal OAuth to enable native Google Docs creation."
            )
        elif self.mode == "unavailable":
            return (
                "No valid Google credentials resolved. All Google integrations are disabled. "
                "Authenticate using 'python -m job_pipeline.setup_oauth' or check your credentials."
            )
        return None

    @property
    def reauth_instruction(self) -> str:
        return "python -m job_pipeline.setup_oauth"

    def __repr__(self) -> str:
        return (
            f"<GoogleAuthContext mode='{self.mode}' "
            f"can_create_drive_files={self.can_create_drive_files} "
            f"can_access_configured_sheet={self.can_access_configured_sheet} "
            f"oauth_failed={self.oauth_failed} is_revoked={self.is_revoked}>"
        )


def get_google_auth_context(
    token_path: Optional[str] = None,
    credentials_path: Optional[str] = None,
    scopes: Optional[List[str]] = None
) -> GoogleAuthContext:
    """Resolves and returns a capability-aware GoogleAuthContext.
    
    Priority:
    1. OAuth 2.0 User Token (token.json or GOOGLE_TOKEN_JSON) -> Personal account quota.
    2. Service Account Key (credentials.json or GOOGLE_CREDENTIALS_JSON) -> Fallback (Sheets only).
    3. Unavailable -> All integrations disabled.
    """
    effective_scopes = scopes or SCOPES
    effective_token_path = token_path or os.environ.get("GOOGLE_TOKEN_PATH", "token.json")
    effective_sa_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    from job_pipeline.logger import log_auth, log_warn

    log_auth(f"Resolving Google API credentials (token: '{effective_token_path}', SA: '{effective_sa_path}')...")

    oauth_creds: Optional[OAuthCredentials] = None
    oauth_failed = False
    oauth_error: Optional[str] = None
    is_revoked = False

    # --- 1. Check OAuth 2.0 User Credentials ---
    raw_token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if raw_token_json and raw_token_json.strip():
        try:
            token_info = json.loads(raw_token_json)
            oauth_creds = OAuthCredentials.from_authorized_user_info(token_info, effective_scopes)
        except Exception as e:
            log_warn(f"Could not parse GOOGLE_TOKEN_JSON: {e}")

    if oauth_creds is None and os.path.exists(effective_token_path):
        try:
            oauth_creds = OAuthCredentials.from_authorized_user_file(effective_token_path, effective_scopes)
        except Exception as e:
            log_warn(f"Could not load OAuth token from '{effective_token_path}': {e}")

    if oauth_creds is not None:
        if oauth_creds.expired and oauth_creds.refresh_token:
            try:
                log_auth("Refreshing expired Google OAuth 2.0 token via Google servers...")
                oauth_creds.refresh(Request())
                if os.path.exists(effective_token_path):
                    with open(effective_token_path, "w", encoding="utf-8") as f:
                        f.write(oauth_creds.to_json())
                log_auth("Google OAuth 2.0 token refreshed and saved.")
            except Exception as ref_err:
                oauth_failed = True
                err_str = str(ref_err)
                oauth_error = err_str
                is_revoked = any(
                    k in err_str.lower()
                    for k in ("invalid_grant", "revoked", "expired", "token has been expired")
                )
                if is_revoked:
                    log_warn(f"OAuth 2.0 token has been expired or revoked (invalid_grant): {ref_err}")
                else:
                    log_warn(f"Failed to refresh OAuth 2.0 token: {ref_err}")
                oauth_creds = None

        if oauth_creds is not None and oauth_creds.valid:
            log_auth("Active credential mode: 'oauth' (Valid Google OAuth 2.0 user credentials active - personal quota).")
            return GoogleAuthContext(
                mode="oauth",
                credentials=oauth_creds,
                token_path=effective_token_path,
                credentials_path=effective_sa_path
            )

    # --- 2. Fallback to Service Account ---
    sa_creds: Optional[ServiceAccountCredentials] = None

    raw_sa_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw_sa_json and raw_sa_json.strip():
        try:
            sa_info = json.loads(raw_sa_json)
            sa_creds = ServiceAccountCredentials.from_service_account_info(sa_info, scopes=effective_scopes)
        except Exception as e:
            log_warn(f"Could not parse GOOGLE_CREDENTIALS_JSON: {e}")

    if sa_creds is None and os.path.exists(effective_sa_path):
        try:
            sa_creds = ServiceAccountCredentials.from_service_account_file(effective_sa_path, scopes=effective_scopes)
        except Exception as e:
            log_warn(f"Could not load Service Account from '{effective_sa_path}': {e}")

    if sa_creds is not None:
        if oauth_failed:
            log_auth(
                "Active credential mode: 'service_account' (FALLBACK). "
                "Warning: Service Account active after OAuth failure. Personal Google Drive file creation is disabled. "
                "Run 'python -m job_pipeline.setup_oauth' to re-authenticate."
            )
        else:
            log_auth(
                "Active credential mode: 'service_account'. "
                "Note: Service Account active. Personal Google Drive file creation is disabled."
            )
        return GoogleAuthContext(
            mode="service_account",
            credentials=sa_creds,
            oauth_failed=oauth_failed,
            oauth_error=oauth_error,
            is_revoked=is_revoked,
            token_path=effective_token_path,
            credentials_path=effective_sa_path
        )

    # --- 3. No usable credentials ---
    log_warn("Active credential mode: 'unavailable'. No valid Google credentials resolved. Google integrations disabled.")
    return GoogleAuthContext(
        mode="unavailable",
        credentials=None,
        oauth_failed=oauth_failed,
        oauth_error=oauth_error,
        is_revoked=is_revoked,
        token_path=effective_token_path,
        credentials_path=effective_sa_path
    )


def get_google_credentials(
    token_path: Optional[str] = None,
    credentials_path: Optional[str] = None,
    scopes: Optional[List[str]] = None
) -> Tuple[Optional[object], str]:
    """Resolves and returns Google API credentials for backwards compatibility.
    
    Returns:
        (credentials_object, auth_type_string)
        auth_type can be 'oauth_user', 'service_account', or 'none'.
    """
    ctx = get_google_auth_context(token_path=token_path, credentials_path=credentials_path, scopes=scopes)
    auth_type_str = "oauth_user" if ctx.mode == "oauth" else ("service_account" if ctx.mode == "service_account" else "none")
    return ctx.credentials, auth_type_str
