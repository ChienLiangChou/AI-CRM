import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
EXPECTED_REDIRECT_URI = (
    "http://127.0.0.1:8000/api/agents/listing-alert-recommendation/gmail/oauth/callback"
)


def load_env() -> None:
    repo_root = Path(__file__).resolve().parent
    env_paths = [
        repo_root / "backend" / ".env",
        repo_root / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exchange a Google OAuth authorization code for Gmail tokens and test Gmail API access.",
        epilog=(
            'Example: python gmail_oauth_test.py "<PASTE_FRESH_CODE_HERE>"\n'
            f"Redirect URI must exactly match your Google Cloud OAuth client: {EXPECTED_REDIRECT_URI}\n"
            "Authorization codes are one-time-use and expire quickly.\n"
            "Pass only the authorization code, not the full redirect URL."
        ),
    )
    parser.add_argument(
        "code",
        nargs="?",
        help=(
            "Fresh one-time Google OAuth authorization code returned to the configured redirect URI. "
            "Pass only the code value, not the full redirect URL."
        ),
    )
    return parser.parse_args(argv)


def load_required_env() -> tuple[str, str, str] | None:
    client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GMAIL_OAUTH_REDIRECT_URI", "").strip()

    missing = [
        env_name
        for env_name, env_value in (
            ("GMAIL_OAUTH_CLIENT_ID", client_id),
            ("GMAIL_OAUTH_CLIENT_SECRET", client_secret),
            ("GMAIL_OAUTH_REDIRECT_URI", redirect_uri),
        )
        if not env_value
    ]
    if missing:
        print_json(
            {
                "error": "missing_env",
                "message": "Missing required environment variables.",
                "missing": missing,
            }
        )
        return None

    return client_id, client_secret, redirect_uri


def parse_response_json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {
            "error": "invalid_json_response",
            "status_code": response.status_code,
            "body": response.text,
        }
    if isinstance(payload, dict):
        return payload
    return {
        "error": "invalid_json_response_shape",
        "status_code": response.status_code,
        "body": payload,
    }


def print_token_response(payload: dict) -> None:
    print_json(
        {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "expires_in": payload.get("expires_in"),
            "scope": payload.get("scope"),
            "token_type": payload.get("token_type"),
        }
    )


def print_exchange_error(payload: dict, *, redirect_uri: str) -> None:
    error_code = str(payload.get("error", "")).strip() or "unknown_error"
    error_description = str(payload.get("error_description", "")).strip()

    print_json(payload)

    if error_code == "invalid_client":
        print("OAuth client credentials were rejected. Check GMAIL_OAUTH_CLIENT_ID and GMAIL_OAUTH_CLIENT_SECRET.")
        return

    if error_code == "redirect_uri_mismatch":
        print(
            "Redirect URI mismatch. "
            "Google Cloud Console OAuth client must allow exactly: "
            f"{redirect_uri}"
        )
        return

    if error_code == "invalid_grant":
        lowered = error_description.lower()
        if "redirect_uri" in lowered and ("mismatch" in lowered or "invalid" in lowered):
            print(
                "Redirect URI mismatch. "
                "Google Cloud Console OAuth client must allow exactly: "
                f"{redirect_uri}"
            )
        else:
            print(
                "Authorization code is invalid, already used, or expired. "
                "Authorization codes are one-time-use. Regenerate a fresh OAuth code and retry immediately."
            )
        return

    print(f"Token exchange failed: {error_code}")


def exchange_code_for_token(auth_code: str) -> dict | None:
    env_values = load_required_env()
    if env_values is None:
        return None
    client_id, client_secret, redirect_uri = env_values

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": auth_code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Network failure during token exchange: {exc}")
        return None

    payload = parse_response_json(response)

    if response.ok:
        print_token_response(payload)
        return payload

    print_exchange_error(payload, redirect_uri=redirect_uri)
    return None


def get_gmail_messages(access_token: str) -> bool:
    try:
        response = requests.get(
            GMAIL_MESSAGES_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={"maxResults": 5},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Network failure during Gmail API test call: {exc}")
        return False

    payload = parse_response_json(response)

    if not response.ok:
        print_json(payload)
        return False

    message_ids = [
        message.get("id")
        for message in payload.get("messages", [])
        if isinstance(message, dict) and message.get("id")
    ][:5]
    print_json({"message_ids": message_ids})
    return True


def main() -> int:
    load_env()
    args = parse_args(sys.argv[1:])

    auth_code = args.code.strip() if args.code else ""
    if not auth_code:
        try:
            auth_code = input("Enter Google authorization code: ").strip()
        except EOFError:
            auth_code = ""

    if not auth_code:
        print("No authorization code provided. Pass only the code value, not the full redirect URL.")
        return 1

    token_payload = exchange_code_for_token(auth_code)
    if token_payload is None:
        return 1

    access_token = str(token_payload.get("access_token", "")).strip()
    if not access_token:
        print("No access_token returned by Google.")
        return 1

    success = get_gmail_messages(access_token)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
