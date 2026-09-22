import argparse
import glob
import os
import sys

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

    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes=SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

        # Save authorized credentials to token file
        with open(args.output_token, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

        print(f"\n[3/3] SUCCESS! OAuth token successfully saved to '{args.output_token}'.")

        # Verify by fetching user info from Drive API
        drive_svc = build("drive", "v3", credentials=creds)
        about = drive_svc.about().get(fields="user, storageQuota").execute()
        user_info = about.get("user", {})
        quota = about.get("storageQuota", {})

        limit_gb = round(int(quota.get("limit", 0)) / (1024 ** 3), 1) if quota.get("limit") else "Unlimited"
        usage_gb = round(int(quota.get("usage", 0)) / (1024 ** 3), 2) if quota.get("usage") else "0"

        print(f"      Authenticated User: {user_info.get('displayName')} ({user_info.get('emailAddress')})")
        print(f"      Drive Quota: {usage_gb} GB used of {limit_gb} GB")
        print("\nAll pipeline Google Drive and Google Sheets operations will now use this personal quota!\n")

    except Exception as e:
        print(f"\nERROR: OAuth authorization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
