"""Local API authentication: signed, expiring, scoped bearer tokens.

Trust model: this protects the API from other network clients and from
browser pages. The signing secret lives in an environment variable or a file
outside version control. Any process running as the SAME OS user can read that
file and the SQLite database, so this does NOT defend against a compromised
host or a hostile process with the same privileges.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

SCOPES = {"read", "write", "evidence"}
MAX_TTL = 30 * 24 * 3600
MIN_SECRET_LEN = 32


class AuthError(Exception):
    def __init__(self, code, message, status=401):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_secret(data_dir=None):
    """Secret from PLANREVIEW_API_SECRET, else a generated file (created once, owner-only where supported)."""
    env = os.environ.get("PLANREVIEW_API_SECRET")
    if env:
        if len(env) < MIN_SECRET_LEN:
            raise RuntimeError(f"PLANREVIEW_API_SECRET must be at least {MIN_SECRET_LEN} characters")
        return env.encode()
    path = Path(data_dir or Path(__file__).resolve().parents[1] / "data") / "api_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return path.read_text().strip().encode()


def _sig(secret: bytes, body: str) -> str:
    return _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())


def mint(secret: bytes, scopes, ttl_seconds: int, now=None) -> str:
    scopes = sorted(set(scopes))
    if not scopes or not set(scopes) <= SCOPES:
        raise ValueError(f"scopes must be a non-empty subset of {sorted(SCOPES)}")
    if not 1 <= ttl_seconds <= MAX_TTL:
        raise ValueError(f"ttl must be 1..{MAX_TTL} seconds")
    exp = int((now if now is not None else time.time()) + ttl_seconds)
    body = f"v1.{'+'.join(scopes)}.{exp}"
    return f"{body}.{_sig(secret, body)}"


def verify(secret: bytes, token: str, now=None):
    """Return (scopes:set, exp:int) or raise AuthError."""
    parts = (token or "").split(".")
    if len(parts) != 4 or parts[0] != "v1":
        raise AuthError("AUTH_INVALID", "Malformed credential")
    _, scope_s, exp_s, sig = parts
    body = f"v1.{scope_s}.{exp_s}"
    if not hmac.compare_digest(sig, _sig(secret, body)):
        raise AuthError("AUTH_INVALID", "Invalid credential")
    try:
        exp = int(exp_s)
    except ValueError:
        raise AuthError("AUTH_INVALID", "Malformed credential")
    if (now if now is not None else time.time()) >= exp:
        raise AuthError("AUTH_EXPIRED", "Credential expired")
    scopes = set(scope_s.split("+"))
    if not scopes <= SCOPES:
        raise AuthError("AUTH_INVALID", "Invalid credential")
    return scopes, exp


def parse_bearer(header):
    if not header:
        raise AuthError("AUTH_REQUIRED", "Authentication required")
    kind, _, value = header.partition(" ")
    if kind.lower() != "bearer" or not value.strip():
        raise AuthError("AUTH_REQUIRED", "Authentication required")
    return value.strip()


def _parse_ttl(s):
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(s[:-1]) * units[s[-1]] if s and s[-1] in units else int(s)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Mint a PlanReview API token (printed once; do not commit or share).")
    ap.add_argument("--scopes", default="read,write", help="comma list of: read, write, evidence")
    ap.add_argument("--ttl", default="8h", help="e.g. 30m, 8h, 7d")
    ap.add_argument("--data", default=None, help="data directory containing api_secret")
    a = ap.parse_args()
    print(mint(load_secret(a.data), a.scopes.split(","), _parse_ttl(a.ttl)))
