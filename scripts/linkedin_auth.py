#!/usr/bin/env python3
"""One-time OAuth2 browser flow for LinkedIn.

Run this once on your Mac to generate linkedin_token.json,
then copy it to your VPS.

Usage:
    python scripts/linkedin_auth.py

Prerequisites:
    1. Create an app at https://www.linkedin.com/developers/apps
    2. Add products: "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn"
    3. Register redirect URI: http://localhost:8585/callback
    4. Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env
"""

import json
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from src.config import settings

TOKEN_PATH = Path("linkedin_token.json")
REDIRECT_URI = "http://localhost:8585/callback"
SCOPES = "openid profile email w_member_social"

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback code."""

    auth_code: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            error = params["error"][0]
            desc = params.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Error: {error}</h1><p>{desc}</p>".encode())
            return

        code = params.get("code", [None])[0]
        if code:
            CallbackHandler.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h1>LinkedIn authorized!</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>No authorization code received</h1>")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default HTTP request logging."""


def main() -> None:
    client_id = settings.linkedin_client_id
    client_secret = settings.linkedin_client_secret

    if not client_id or not client_secret:
        print("ERROR: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env")
        print("Create an app at https://www.linkedin.com/developers/apps")
        sys.exit(1)

    if TOKEN_PATH.exists():
        print(f"Token already exists at {TOKEN_PATH}")
        response = input("Overwrite? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    # Build authorization URL
    auth_params = (
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES}"
    )
    full_auth_url = AUTH_URL + auth_params

    print("Opening browser for LinkedIn OAuth consent...")
    print(f"If the browser doesn't open, visit:\n{full_auth_url}\n")
    webbrowser.open(full_auth_url)

    # Start local server to catch the callback
    server = HTTPServer(("localhost", 8585), CallbackHandler)
    print("Waiting for callback on http://localhost:8585/callback ...")
    server.handle_request()

    code = CallbackHandler.auth_code
    if not code:
        print("ERROR: No authorization code received.")
        sys.exit(1)

    print("Authorization code received. Exchanging for token...")

    # Exchange code for token
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"ERROR: Token exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 5184000)  # default 60 days

    # Fetch user info
    print("Fetching user profile...")
    userinfo_resp = httpx.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )

    person_id = ""
    name = ""
    email = ""
    if userinfo_resp.status_code == 200:
        info = userinfo_resp.json()
        person_id = info.get("sub", "")
        name = info.get("name", "")
        email = info.get("email", "")
        print(f"Authenticated as: {name} ({email})")
    else:
        print(f"Warning: Could not fetch user info ({userinfo_resp.status_code})")

    # Save token
    saved = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
        "refresh_token": token_data.get("refresh_token", ""),
        "person_id": person_id,
        "name": name,
        "email": email,
    }
    TOKEN_PATH.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    print(f"\nToken saved to {TOKEN_PATH}")
    print(f"Expires in {expires_in // 86400} days.")
    print("\nTo deploy on your VPS, copy this file:")
    print(f"  scp {TOKEN_PATH} your-vps:/home/nella/app/{TOKEN_PATH}")


if __name__ == "__main__":
    main()
