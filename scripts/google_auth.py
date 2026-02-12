#!/usr/bin/env python3
"""One-time OAuth2 browser flow for Google Workspace APIs.

Run this once per account on your Mac to generate a token file,
then copy it to your VPS.

Usage:
    python scripts/google_auth.py --account work
    python scripts/google_auth.py --account personal
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import settings
from src.integrations.google_auth import GoogleAuthManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Google OAuth2 authentication for Nella")
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g. 'work', 'personal'). "
        "Token saved to auth_tokens/google_<account>_auth_token.json",
    )
    args = parser.parse_args()

    account = args.account
    creds_path = Path(settings.google_credentials_path)
    token_path = Path(f"auth_tokens/google_{account}_auth_token.json")

    if not creds_path.exists():
        print(f"ERROR: credentials file not found at {creds_path}")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        sys.exit(1)

    if token_path.exists():
        print(f"Token already exists at {token_path}")
        response = input("Overwrite? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    print(f"Authenticating account: {account}")
    print(f"Requesting scopes: {GoogleAuthManager.SCOPES}")
    print("Opening browser for Google OAuth consent...")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(creds_path),
        scopes=GoogleAuthManager.SCOPES,
    )
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nToken saved to {token_path}")


if __name__ == "__main__":
    main()
