#!/usr/bin/env python3
"""Drive Google's installed-app OAuth loopback flow and write the
resulting refresh token to a JSON file consumable by `bouncer
issue-token --credentials-file`.

Stdlib-only — no third-party dependencies. Tested on Python 3.7+.
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import socket
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

GOOGLE_SCOPE_PREFIX = "https://www.googleapis.com/auth/"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def expand_scopes(raw):
    """Split a comma-separated scope string and prefix short names
    with `https://www.googleapis.com/auth/`. Full URIs pass through
    unchanged."""
    return [
        s if s.startswith("http") else GOOGLE_SCOPE_PREFIX + s
        for s in (chunk.strip() for chunk in raw.split(","))
        if s
    ]


def read_client_secrets(path):
    """Read a Google client_secrets.json. The file wraps client_id
    / client_secret under either an `installed` key (Desktop apps)
    or a `web` key (Web apps)."""
    data = json.loads(Path(path).read_text())
    for key in ("installed", "web"):
        if key in data:
            return data[key]
    raise ValueError("client_secrets.json: missing 'installed' or 'web' section")


def pkce_pair():
    """RFC 7636 S256 PKCE verifier + challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def build_auth_url(client_id, redirect_uri, scopes, state, code_challenge):
    """Construct Google's authorization URL for the installed-app flow."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return GOOGLE_AUTH_URI + "?" + urllib.parse.urlencode(params)


def credentials_payload(client_id, client_secret, refresh_token):
    """Google-shaped credentials dict. `bouncer issue-token` reads
    only `refresh_token`; the rest is included so other OAuth2
    clients can consume the file directly."""
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": GOOGLE_TOKEN_URI,
    }


def pick_free_port():
    """Bind a free TCP port and release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_callback(port):
    """Run a one-shot HTTP server on the loopback port and return
    the parsed query parameters from the OAuth redirect."""
    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            captured["code"] = params.get("code", [None])[0]
            captured["state"] = params.get("state", [None])[0]
            captured["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Authorization complete</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.handle_request()
    finally:
        server.server_close()
    return captured


def exchange_code(client_id, client_secret, code, redirect_uri, code_verifier):
    """Exchange the authorization code for access + refresh tokens."""
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        GOOGLE_TOKEN_URI,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Capture a Google OAuth refresh token via the installed-app flow."
    )
    parser.add_argument(
        "--client-secrets",
        required=True,
        type=Path,
        help="path to client_secrets.json (downloaded from APIs & Services > Credentials)",
    )
    parser.add_argument(
        "--scopes",
        required=True,
        help="comma-separated scopes (e.g. 'gmail.modify,drive,calendar')",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="path to write the refresh credentials JSON",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="loopback port (default 0 = pick a free port)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    config = read_client_secrets(args.client_secrets)
    scopes = expand_scopes(args.scopes)
    port = args.port or pick_free_port()
    redirect_uri = "http://127.0.0.1:" + str(port)
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()

    auth_url = build_auth_url(
        client_id=config["client_id"],
        redirect_uri=redirect_uri,
        scopes=scopes,
        state=state,
        code_challenge=challenge,
    )

    print("Opening browser for Google sign-in...", file=sys.stderr)
    print("If the browser does not open, visit:", file=sys.stderr)
    print(auth_url, file=sys.stderr)
    webbrowser.open(auth_url)

    captured = wait_for_callback(port)

    if captured.get("error"):
        print("Google returned an error: " + captured["error"], file=sys.stderr)
        return 1
    if captured.get("state") != state:
        print("error: state mismatch on the OAuth callback (possible CSRF)", file=sys.stderr)
        return 1

    tokens = exchange_code(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        code=captured["code"],
        redirect_uri=redirect_uri,
        code_verifier=verifier,
    )

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(
            "error: Google did not return a refresh token. Revoke the app at "
            "https://myaccount.google.com/permissions and re-run.",
            file=sys.stderr,
        )
        return 1

    payload = credentials_payload(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        refresh_token=refresh_token,
    )
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    args.out.chmod(0o600)
    print("wrote refresh credentials to " + str(args.out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
