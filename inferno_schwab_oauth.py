from __future__ import annotations

"""Local Schwab OAuth helper for the Inferno desk.

This script is intentionally narrow and boring:

- read local credentials from the ignored `.env.schwab` file
- generate the Schwab authorization URL
- exchange a returned authorization code for tokens
- refresh the access token when needed
- store tokens in the ignored `.secrets/schwab_token.json` vault

It does not call account, order, preview, or trading endpoints. This is the
market-data bridge only, so the desk can pull option-chain data without making
thinkorswim desktop exports do all the work.
"""

import argparse
import base64
from contextlib import contextmanager
import gzip
import json
import os
import ssl
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from inferno_io import atomic_write_json


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.schwab"
DEFAULT_AUTH_BASE_URL = "https://api.schwabapi.com/v1/oauth"
DEFAULT_API_BASE_URL = "https://api.schwabapi.com"
DEFAULT_REDIRECT_URI = "https://127.0.0.1"
DEFAULT_TOKEN_FILE = ROOT / ".secrets" / "schwab_token.json"
ACCESS_TOKEN_REFRESH_BUFFER_SECONDS = 300


class SchwabOAuthError(RuntimeError):
    """Recoverable OAuth failure for library callers and CLI rendering."""


def https_context() -> ssl.SSLContext:
    """Return a certificate-validating HTTPS context for Schwab requests.

    Some local Python installs on macOS do not know where the system CA bundle
    lives. When the Backtest venv includes certifi, use its maintained CA file
    rather than disabling verification.
    """
    try:
        import certifi  # type: ignore[import-not-found]

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def parse_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse a small shell-style env file without executing it.

    The parser only supports the simple `KEY=value` shape we write by hand for
    this project. That keeps secrets out of shell history and avoids importing
    third-party dotenv dependencies.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_config(path: Path = ENV_FILE) -> dict[str, Any]:
    """Load Schwab OAuth config from `.env.schwab` plus safe defaults."""
    env = parse_env_file(path)
    client_id = env.get("SCHWAB_CLIENT_ID") or os.environ.get("SCHWAB_CLIENT_ID", "")
    client_secret = env.get("SCHWAB_CLIENT_SECRET") or os.environ.get("SCHWAB_CLIENT_SECRET", "")
    token_file = Path(
        env.get("SCHWAB_TOKEN_FILE")
        or os.environ.get("SCHWAB_TOKEN_FILE")
        or str(DEFAULT_TOKEN_FILE)
    ).expanduser()
    return {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "redirect_uri": (
            env.get("SCHWAB_REDIRECT_URI")
            or os.environ.get("SCHWAB_REDIRECT_URI")
            or DEFAULT_REDIRECT_URI
        ).strip(),
        "auth_base_url": (
            env.get("SCHWAB_AUTH_BASE_URL")
            or os.environ.get("SCHWAB_AUTH_BASE_URL")
            or DEFAULT_AUTH_BASE_URL
        ).strip().rstrip("/"),
        "api_base_url": (
            env.get("SCHWAB_API_BASE_URL")
            or os.environ.get("SCHWAB_API_BASE_URL")
            or DEFAULT_API_BASE_URL
        ).strip().rstrip("/"),
        "token_file": token_file,
    }


def require_config(config: dict[str, Any]) -> None:
    """Fail early if the local secret file is missing required values."""
    missing = [
        name
        for name, value in (
            ("SCHWAB_CLIENT_ID", config.get("client_id")),
            ("SCHWAB_CLIENT_SECRET", config.get("client_secret")),
            ("SCHWAB_REDIRECT_URI", config.get("redirect_uri")),
        )
        if not value
    ]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing Schwab OAuth config in .env.schwab: {joined}")


def authorization_url(config: dict[str, Any]) -> str:
    """Build the one-time Schwab consent URL."""
    require_config(config)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
        }
    )
    return f"{config['auth_base_url']}/authorize?{query}"


def extract_authorization_code(value: str) -> str:
    """Extract `code` from a full redirect URL or return a raw pasted code."""
    text = value.strip()
    if not text:
        raise SystemExit("No authorization code or redirect URL was provided.")
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc and not parsed.query:
        raise SystemExit(
            "That URL does not include a Schwab authorization code. "
            "Paste the full redirect URL with '?code=...' from the browser address bar."
        )
    if parsed.query:
        code = parse_qs(parsed.query).get("code", [""])[0].strip()
        if code:
            return code
        error = parse_qs(parsed.query).get("error", [""])[0].strip()
        if error:
            raise SystemExit(f"Schwab authorization returned error={error}")
    return text


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Return the OAuth Basic auth header without logging secrets."""
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def request_token(config: dict[str, Any], form: dict[str, str]) -> dict[str, Any]:
    """POST a token request to Schwab and return the parsed JSON payload."""
    require_config(config)
    body = urlencode(form).encode("utf-8")
    request = Request(
        f"{config['auth_base_url']}/token",
        data=body,
        headers={
            "Authorization": _basic_auth_header(config["client_id"], config["client_secret"]),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30, context=https_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        if str(exc.headers.get("Content-Encoding", "")).lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        body_text = raw.decode("utf-8", errors="replace").strip()
        try:
            body = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            body = {"response": body_text[:500]}
        error = body.get("error") or "unknown"
        description = body.get("error_description") or body.get("message") or body.get("response") or ""
        detail = f"Schwab OAuth token request failed: HTTP {exc.code} {error}"
        if description:
            detail += f" | {description}"
        detail += " | Generate a fresh auth URL and exchange the redirect URL immediately; codes are one-use and short-lived."
        raise SchwabOAuthError(detail) from exc


def parse_timestamp(value: Any) -> datetime | None:
    """Parse one OAuth timestamp into UTC."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seconds_remaining(value: Any, *, now: datetime | None = None) -> float | None:
    """Return seconds until an OAuth timestamp, or None when unknown."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    current = now or datetime.now(timezone.utc)
    return (parsed - current).total_seconds()


def access_token_needs_refresh(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    buffer_seconds: int = ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
) -> bool:
    """Refresh only when the access token is missing or near expiration."""
    if not payload.get("access_token"):
        return True
    remaining = seconds_remaining(payload.get("expires_at"), now=now)
    return remaining is None or remaining <= buffer_seconds


def enrich_token_payload(
    payload: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    fresh_authorization: bool = False,
) -> dict[str, Any]:
    """Add local expiry metadata while preserving refresh tokens on refresh.

    Access tokens expire quickly, so the metadata lets the desk know whether the
    token is fresh without printing the token itself. Schwab may not return a new
    refresh token on every refresh call, so we preserve the old one when needed.
    """
    now = datetime.now(timezone.utc)
    enriched = dict(previous or {})
    enriched.update(payload)
    if not enriched.get("refresh_token") and previous and previous.get("refresh_token"):
        enriched["refresh_token"] = previous["refresh_token"]
    expires_in = int(float(payload.get("expires_in") or 0))
    if expires_in > 0:
        enriched["expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    refresh_expires_in = int(float(payload.get("refresh_token_expires_in") or 0))
    if refresh_expires_in > 0:
        enriched["refresh_token_expires_at"] = (
            now + timedelta(seconds=refresh_expires_in)
        ).isoformat()
    refresh_rotated = bool(
        payload.get("refresh_token")
        and previous
        and payload.get("refresh_token") != previous.get("refresh_token")
    )
    if fresh_authorization or refresh_rotated or not enriched.get("refresh_token_issued_at"):
        enriched["refresh_token_issued_at"] = now.isoformat()
        enriched["refresh_token_issued_at_estimated"] = not fresh_authorization
    enriched.pop("last_refresh_error", None)
    enriched.pop("last_refresh_error_at", None)
    enriched["reauthorization_required"] = False
    enriched["token_obtained_at"] = now.isoformat()
    return enriched


def read_token_file(path: Path) -> dict[str, Any]:
    """Load the ignored token file, returning an empty dict when absent."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - status should be safe, not noisy.
        return {}


def write_token_file(config: dict[str, Any], payload: dict[str, Any]) -> Path:
    """Write the OAuth token payload to the ignored local vault."""
    path: Path = config["token_file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    atomic_write_json(path, payload)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


@contextmanager
def token_refresh_lock(config: dict[str, Any]) -> Iterator[None]:
    """Serialize token refreshes across launch agents and manual commands."""
    import fcntl

    token_file: Path = config["token_file"]
    lock_path = token_file.with_suffix(token_file.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(lock_path.parent, stat.S_IRWXU)
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, stat.S_IRUSR | stat.S_IWUSR)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def refresh_error_requires_reauthorization(error: Exception) -> bool:
    """Identify Schwab's terminal refresh-token failures."""
    detail = str(error).lower()
    return (
        "invalid_grant" in detail
        or "refresh token is invalid" in detail
        or "refresh token is expired" in detail
        or "refresh token is invalid, expired or revoked" in detail
    )


def record_refresh_error(
    config: dict[str, Any],
    existing: dict[str, Any],
    error: Exception,
) -> None:
    """Persist safe failure metadata without exposing or deleting tokens."""
    updated = dict(existing)
    updated["last_refresh_error"] = str(error)
    updated["last_refresh_error_at"] = datetime.now(timezone.utc).isoformat()
    if refresh_error_requires_reauthorization(error):
        updated["reauthorization_required"] = True
    write_token_file(config, updated)


def exchange_code(config: dict[str, Any], code_or_url: str) -> Path:
    """Exchange a Schwab redirect code for local access/refresh tokens."""
    code = extract_authorization_code(code_or_url)
    payload = request_token(
        config,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["redirect_uri"],
        },
    )
    enriched = enrich_token_payload(payload, fresh_authorization=True)
    return write_token_file(config, enriched)


def refresh_access_token(config: dict[str, Any], *, force: bool = False) -> Path:
    """Refresh once when needed, serialized across every desk process."""
    with token_refresh_lock(config):
        existing = read_token_file(config["token_file"])
        if not force and not access_token_needs_refresh(existing):
            return config["token_file"]
        if existing.get("reauthorization_required"):
            raise SchwabOAuthError(
                "Schwab reauthorization is required. Run the OAuth restart once "
                "and exchange only the newest redirect URL."
            )
        refresh_token = str(existing.get("refresh_token") or "").strip()
        if not refresh_token:
            raise SchwabOAuthError(
                "No refresh_token found. Run the authorization exchange first."
            )
        try:
            payload = request_token(
                config,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        except Exception as exc:
            record_refresh_error(config, existing, exc)
            raise
        enriched = enrich_token_payload(payload, previous=existing)
        return write_token_file(config, enriched)


def token_status(config: dict[str, Any]) -> dict[str, Any]:
    """Return safe token/config health without exposing secrets."""
    token_file: Path = config["token_file"]
    payload = read_token_file(token_file)
    now = datetime.now(timezone.utc)
    access_remaining = seconds_remaining(payload.get("expires_at"), now=now)
    refresh_issued_at = payload.get("refresh_token_issued_at")
    refresh_issued_estimated = bool(payload.get("refresh_token_issued_at_estimated"))
    if not refresh_issued_at and payload.get("token_obtained_at"):
        refresh_issued_at = payload.get("token_obtained_at")
        refresh_issued_estimated = True
    refresh_expires_at = payload.get("refresh_token_expires_at")
    issued_at = parse_timestamp(refresh_issued_at)
    refresh_age_seconds = (
        (now - issued_at).total_seconds() if issued_at is not None else None
    )
    refresh_remaining = seconds_remaining(refresh_expires_at, now=now)
    reauthorization_required = bool(payload.get("reauthorization_required")) or (
        refresh_remaining is not None and refresh_remaining <= 0
    )
    return {
        "envFile": str(ENV_FILE),
        "envFileExists": ENV_FILE.exists(),
        "clientIdConfigured": bool(config.get("client_id")),
        "clientSecretConfigured": bool(config.get("client_secret")),
        "redirectUri": config.get("redirect_uri"),
        "tokenFile": str(token_file),
        "tokenFileExists": token_file.exists(),
        "accessTokenPresent": bool(payload.get("access_token")),
        "refreshTokenPresent": bool(payload.get("refresh_token")),
        "accessTokenExpiresAt": payload.get("expires_at"),
        "accessTokenSecondsRemaining": (
            round(access_remaining, 1) if access_remaining is not None else None
        ),
        "accessTokenNeedsRefresh": access_token_needs_refresh(payload, now=now),
        "refreshTokenIssuedAt": refresh_issued_at,
        "refreshTokenIssuedAtEstimated": refresh_issued_estimated,
        "refreshTokenAgeSeconds": (
            round(refresh_age_seconds, 1) if refresh_age_seconds is not None else None
        ),
        "refreshTokenExpiresAt": refresh_expires_at,
        "refreshTokenExpiryReportedBySchwab": bool(refresh_expires_at),
        "refreshTokenSecondsRemaining": (
            round(refresh_remaining, 1) if refresh_remaining is not None else None
        ),
        "reauthorizationRequired": reauthorization_required,
        "lastRefreshErrorAt": payload.get("last_refresh_error_at"),
        "lastRefreshError": payload.get("last_refresh_error"),
    }


def print_status(status: dict[str, Any]) -> None:
    """Print a human-readable token status report with no secret material."""
    for key, value in status.items():
        print(f"{key}: {value}")


def main() -> int:
    """Run the Schwab OAuth helper CLI."""
    parser = argparse.ArgumentParser(description="Schwab OAuth helper for read-only option-chain data.")
    parser.add_argument(
        "command",
        choices=("auth-url", "exchange", "restart", "refresh", "ensure", "status"),
        help="OAuth action to run.",
    )
    parser.add_argument(
        "--code",
        help="Full Schwab redirect URL or raw authorization code for the exchange command.",
    )
    args = parser.parse_args()

    config = load_config()
    try:
        if args.command == "auth-url":
            print(authorization_url(config))
            return 0
        if args.command in {"exchange", "restart"}:
            if args.command == "restart":
                print("Open this URL and complete Schwab consent:")
                print(authorization_url(config))
            code_or_url = args.code or input(
                "Paste the newest full Schwab redirect URL or code: "
            ).strip()
            path = exchange_code(config, code_or_url)
            print(f"Schwab token saved safely to {path}")
            print_status(token_status(config))
            return 0
        if args.command == "refresh":
            path = refresh_access_token(config, force=True)
            print(f"Schwab token refreshed safely at {path}")
            print_status(token_status(config))
            return 0
        if args.command == "ensure":
            path = refresh_access_token(config)
            print(f"Schwab token is ready at {path}")
            print_status(token_status(config))
            return 0
        print_status(token_status(config))
        return 0
    except SchwabOAuthError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
