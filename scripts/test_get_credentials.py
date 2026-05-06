"""Unit tests for get_credentials.py — stdlib unittest only."""

import json
import tempfile
import unittest
from pathlib import Path

from get_credentials import (
    GOOGLE_AUTH_URI,
    GOOGLE_TOKEN_URI,
    build_auth_url,
    credentials_payload,
    expand_scopes,
    pkce_pair,
    read_client_secrets,
)


class TestExpandScopes(unittest.TestCase):
    def test_prefixes_short_names(self):
        self.assertEqual(
            expand_scopes("gmail.modify,drive"),
            [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/drive",
            ],
        )

    def test_passes_full_urls_through(self):
        full = "https://www.googleapis.com/auth/calendar"
        self.assertEqual(expand_scopes(full), [full])

    def test_strips_whitespace_and_skips_empties(self):
        self.assertEqual(
            expand_scopes(" gmail.modify , , drive "),
            [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/drive",
            ],
        )


class TestPkcePair(unittest.TestCase):
    def test_verifier_and_challenge_are_distinct(self):
        verifier, challenge = pkce_pair()
        self.assertNotEqual(verifier, challenge)
        self.assertGreater(len(verifier), 40)
        self.assertGreater(len(challenge), 40)

    def test_challenge_is_url_safe_base64(self):
        _verifier, challenge = pkce_pair()
        for ch in ("=", "+", "/"):
            self.assertNotIn(ch, challenge)


class TestBuildAuthUrl(unittest.TestCase):
    def test_includes_required_params(self):
        url = build_auth_url(
            client_id="cid",
            redirect_uri="http://127.0.0.1:1234",
            scopes=["s1", "s2"],
            state="st",
            code_challenge="cc",
        )
        self.assertTrue(url.startswith(GOOGLE_AUTH_URI + "?"))
        for needle in (
            "client_id=cid",
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A1234",
            "scope=s1+s2",
            "access_type=offline",
            "prompt=consent",
            "state=st",
            "code_challenge=cc",
            "code_challenge_method=S256",
            "response_type=code",
        ):
            self.assertIn(needle, url)


class TestReadClientSecrets(unittest.TestCase):
    def _write(self, payload):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(payload, f)
        f.close()
        return Path(f.name)

    def test_reads_installed_section(self):
        path = self._write({"installed": {"client_id": "cid", "client_secret": "sec"}})
        self.assertEqual(
            read_client_secrets(path),
            {"client_id": "cid", "client_secret": "sec"},
        )

    def test_reads_web_section(self):
        path = self._write({"web": {"client_id": "wid", "client_secret": "wsec"}})
        self.assertEqual(read_client_secrets(path)["client_id"], "wid")

    def test_rejects_missing_section(self):
        path = self._write({"foo": "bar"})
        with self.assertRaises(ValueError):
            read_client_secrets(path)


class TestCredentialsPayload(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(
            credentials_payload(client_id="cid", client_secret="sec", refresh_token="1//rt"),
            {
                "client_id": "cid",
                "client_secret": "sec",
                "refresh_token": "1//rt",
                "token_uri": GOOGLE_TOKEN_URI,
            },
        )


if __name__ == "__main__":
    unittest.main()
