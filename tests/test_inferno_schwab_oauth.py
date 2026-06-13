from __future__ import annotations

"""Regression tests for the Schwab OAuth helper."""

import io
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

        with patch.object(oauth, "urlopen", side_effect=error), self.assertRaises(SystemExit) as ctx:
            oauth.request_token(config, {"grant_type": "authorization_code", "code": "bad"})

        self.assertIn("HTTP 400 invalid_grant", str(ctx.exception))
        self.assertIn("Bad authorization code", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
