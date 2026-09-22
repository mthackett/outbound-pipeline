import json
import os
from typing import List, Optional, Tuple

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


def get_google_credentials(
    token_path: Optional[str] = None,
    credentials_path: Optional[str] = None,
    scopes: Optional[List[str]] = None
) -> Tuple[Optional[object], str]:
    """Resolves and returns Google API credentials.
    
    Priority:
    1. OAuth 2.0 User Token (token.json or GOOGLE_TOKEN_JSON) -> Personal account quota.
    2. Service Account Key (credentials.json or GOOGLE_CREDENTIALS_JSON) -> Fallback.
    
    Returns:
        (credentials_object, auth_type_string)
        auth_type can be 'oauth_user', 'service_account', or 'none'.
    """
    effective_scopes = scopes or SCOPES
    effective_token_path = token_path or os.environ.get("GOOGLE_TOKEN_PATH", "token.json")
    effective_sa_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    # --- 1. Check OAuth 2.0 User Credentials ---
    oauth_creds: Optional[OAuthCredentials] = None

    # Check env var for serialized token
    raw_token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if raw_token_json and raw_token_json.strip():
        try:
            token_info = json.loads(raw_token_json)
            oauth_creds = OAuthCredentials.from_authorized_user_info(token_info, effective_scopes)
        except Exception as e:
            print(f"WARNING: Could not parse GOOGLE_TOKEN_JSON: {e}")

    # Check local token.json file
    if oauth_creds is None and os.path.exists(effective_token_path):
        try:
            oauth_creds = OAuthCredentials.from_authorized_user_file(effective_token_path, effective_scopes)
        except Exception as e:
            print(f"WARNING: Could not load OAuth token from '{effective_token_path}': {e}")

    # Refresh OAuth token if expired
    if oauth_creds is not None:
        if oauth_creds.expired and oauth_creds.refresh_token:
            try:
                oauth_creds.refresh(Request())
                if os.path.exists(effective_token_path):
                    with open(effective_token_path, "w", encoding="utf-8") as f:
                        f.write(oauth_creds.to_json())
            except Exception as ref_err:
                print(f"WARNING: Failed to refresh OAuth 2.0 token: {ref_err}")
                oauth_creds = None

        if oauth_creds is not None and oauth_creds.valid:
            return oauth_creds, "oauth_user"

    # --- 2. Fallback to Service Account ---
    sa_creds: Optional[ServiceAccountCredentials] = None

    raw_sa_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw_sa_json and raw_sa_json.strip():
        try:
            sa_info = json.loads(raw_sa_json)
            sa_creds = ServiceAccountCredentials.from_service_account_info(sa_info, scopes=effective_scopes)
        except Exception as e:
            print(f"WARNING: Could not parse GOOGLE_CREDENTIALS_JSON: {e}")

    if sa_creds is None and os.path.exists(effective_sa_path):
        try:
            sa_creds = ServiceAccountCredentials.from_service_account_file(effective_sa_path, scopes=effective_scopes)
        except Exception as e:
            print(f"WARNING: Could not load Service Account from '{effective_sa_path}': {e}")

    if sa_creds is not None:
        return sa_creds, "service_account"

    return None, "none"
