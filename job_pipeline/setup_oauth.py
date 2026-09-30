import argparse
import glob
import os
import sys
from typing import Tuple, Dict, Any, Optional

# Prevent ScopeChangedError when Google server normalizes or reorders scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from job_pipeline.adapters.secondary.google_auth import SCOPES


def find_client_secrets_file(explicit_path: str = "") -> str:
    """Finds the OAuth 2.0 client secrets JSON file."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path

    # Check common default filenames
    candidates = ["client_secret.json", "client_secrets.json"]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Check glob pattern for downloaded GCP files (e.g., client_secret_*.json)
    matches = glob.glob("client_secret*.json")
    if matches:
        return matches[0]

    return ""


def run_oauth_flow(
    client_secrets_path: Optional[str] = None,
    output_token_path: str = "token.json",
    port: int = 0
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Runs the Google OAuth 2.0 flow using InstalledAppFlow and writes token.json.
    
    Returns:
        (success: bool, message: str, user_info: Optional[dict])
    """
    secrets_path = find_client_secrets_file(client_secrets_path or "")
    if not secrets_path:
        return False, "No OAuth 2.0 client secret JSON file found (e.g. client_secret.json).", None

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes=SCOPES)
        creds = flow.run_local_server(port=port, prompt="consent")

        with open(output_token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

        # Verify info
        info = {}
        try:
            drive_svc = build("drive", "v3", credentials=creds)
            about = drive_svc.about().get(fields="user, storageQuota").execute()
            user_info = about.get("user", {})
            quota = about.get("storageQuota", {})
            limit_gb = round(int(quota.get("limit", 0)) / (1024 ** 3), 1) if quota.get("limit") else "Unlimited"
            usage_gb = round(int(quota.get("usage", 0)) / (1024 ** 3), 2) if quota.get("usage") else "0"
            info = {
                "display_name": user_info.get("displayName"),
                "email": user_info.get("emailAddress"),
                "usage_gb": usage_gb,
                "limit_gb": limit_gb
            }
        except Exception:
            pass

        return True, f"OAuth token successfully saved to '{output_token_path}'.", info
    except Exception as e:
        return False, str(e), None


def main():
    parser = argparse.ArgumentParser(description="Authorize Outbound Pipeline with Google OAuth 2.0 (User Account)")
    parser.add_argument(
        "--client-secrets",
        "-c",
        default="",
        help="Path to the OAuth 2.0 client secret JSON file downloaded from Google Cloud Console."
    )
    parser.add_argument(
        "--output-token",
        "-o",
        default="token.json",
        help="Path to save the generated token.json (default: token.json)"
    )
    args = parser.parse_args()

    client_secrets_path = find_client_secrets_file(args.client_secrets)

    if not client_secrets_path:
        print("\n" + "=" * 70)
        print("ERROR: No OAuth 2.0 client secret JSON file found.")
        print("=" * 70)
        print("\nTo set up OAuth 2.0 for your personal Google Account:")
        print("1. Go to Google Cloud Console (https://console.cloud.google.com/)")
        print("2. Ensure your project is selected ('job-application-tracker-471402')")
        print("3. Go to 'APIs & Services' -> 'OAuth consent screen'")
        print("   - Ensure User Type is 'External' and your email is in 'Test users'")
        print("4. Go to 'APIs & Services' -> 'Credentials'")
        print("5. Click '+ CREATE CREDENTIALS' -> 'OAuth client ID'")
        print("   - Application type: 'Desktop app'")
        print("   - Name: 'Job Application Tracker Desktop'")
        print("6. Click 'CREATE', then click 'DOWNLOAD JSON'")
        print(f"7. Save the downloaded file in this project root as 'client_secret.json'")
        print("8. Re-run this script: python -m job_pipeline.setup_oauth\n")
        sys.exit(1)

    print(f"\n[1/3] Found client secrets file: {client_secrets_path}")
    print("[2/3] Initiating Google OAuth 2.0 authorization flow...")
    print("      Your default web browser will open. Please sign in with your Google account")
    print("      and grant permission to access Google Drive and Google Sheets.\n")

    success, msg, info = run_oauth_flow(client_secrets_path, output_token_path=args.output_token)
    if not success:
        print(f"\nERROR: OAuth authorization failed: {msg}")
        sys.exit(1)

    print(f"\n[3/3] SUCCESS! {msg}")
    if info:
        print(f"      Authenticated User: {info.get('display_name')} ({info.get('email')})")
        print(f"      Drive Quota: {info.get('usage_gb')} GB used of {info.get('limit_gb')} GB")
    print("\nAll pipeline Google Drive and Google Sheets operations will now use this personal quota!\n")


if __name__ == "__main__":
    main()
