from __future__ import annotations

"""Regression tests for the Schwab OAuth helper."""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import inferno_schwab_oauth as oauth


class SchwabOauthTests(unittest.TestCase):
    def test_extract_authorization_code_decodes_trailing_at(self) -> None:
        url = "https://127.0.0.1/?code=C0.example%40&session=abc"

        self.assertEqual(oauth.extract_authorization_code(url), "C0.example@")

    def test_extract_authorization_code_rejects_url_without_code(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            oauth.extract_authorization_code("https://127.0.0.1")

        self.assertIn("?code=...", str(ctx.exception))

    def test_request_token_surfaces_schwab_error_body(self) -> None:
        config = {
            "client_id": "id",
            "client_secret": "secret",
            "redirect_uri": "https://127.0.0.1",
            "auth_base_url": "https://api.schwabapi.com/v1/oauth",
        }
        error = HTTPError(
            url="https://api.schwabapi.com/v1/oauth/token",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(
                b'{"error":"invalid_grant","error_description":"Bad authorization code"}'
            ),
        )

        with patch.object(oauth, "urlopen", side_effect=error), self.assertRaises(oauth.SchwabOAuthError) as ctx:
            oauth.request_token(config, {"grant_type": "authorization_code", "code": "bad"})

        self.assertIn("HTTP 400 invalid_grant", str(ctx.exception))
        self.assertIn("Bad authorization code", str(ctx.exception))

    def test_access_token_refresh_is_skipped_while_fresh(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "access_token": "access",
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
        }

        self.assertFalse(oauth.access_token_needs_refresh(payload, now=now))

    def test_refresh_is_serialized_and_skips_network_for_fresh_token(self) -> None:
        with TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token.json"
            config = {
                "client_id": "id",
                "client_secret": "secret",
                "redirect_uri": "https://127.0.0.1",
                "auth_base_url": "https://api.schwabapi.com/v1/oauth",
                "token_file": token_file,
            }
            oauth.write_token_file(
                config,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=20)
                    ).isoformat(),
                },
            )
            with patch.object(oauth, "request_token") as request:
                oauth.refresh_access_token(config)

            request.assert_not_called()

    def test_invalid_refresh_marks_reauthorization_required(self) -> None:
        with TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token.json"
            config = {
                "client_id": "id",
                "client_secret": "secret",
                "redirect_uri": "https://127.0.0.1",
                "auth_base_url": "https://api.schwabapi.com/v1/oauth",
                "token_file": token_file,
            }
            oauth.write_token_file(
                config,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                },
            )
            failure = oauth.SchwabOAuthError(
                "HTTP 400 invalid_grant | Refresh token is invalid, expired or revoked"
            )
            with patch.object(oauth, "request_token", side_effect=failure), self.assertRaises(
                oauth.SchwabOAuthError
            ):
                oauth.refresh_access_token(config)

            self.assertTrue(oauth.token_status(config)["reauthorizationRequired"])

    def test_fresh_authorization_tracks_refresh_token_issuance(self) -> None:
        payload = oauth.enrich_token_payload(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 1800,
            },
            fresh_authorization=True,
        )

        self.assertTrue(payload["refresh_token_issued_at"])
        self.assertNotIn("refresh_token_expires_at", payload)


if __name__ == "__main__":
    unittest.main()
