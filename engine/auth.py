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
import re
import secrets
import time
from pathlib import Path

SCOPES = {"read", "write", "evidence"}
MAX_TTL = 30 * 24 * 3600
MIN_SECRET_LEN = 32


class AuthError(Exception):
    def __init__(self, code, message, status=401, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after = code, message, status, retry_after


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
        _owner_only(path)
    return path.read_text().strip().encode()


def _owner_only(path):
    """0o600 is meaningless on Windows: drop inherited ACLs and grant only the current user (best effort)."""
    if os.name != "nt":
        return
    import subprocess

    try:
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:F"], capture_output=True, timeout=15)
    except Exception:
        pass


def _sig(secret: bytes, body: str) -> str:
    return _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())


_SUB = re.compile(r"^[A-Za-z0-9_@\-]{1,64}$")


def mint(secret: bytes, scopes, ttl_seconds: int, now=None, sub="local", jti=None) -> str:
    """v2 token: v2.<sub>.<scopes>.<exp>.<jti>.<sig>. `sub` is the accountable identity; `jti` allows revocation."""
    scopes = sorted(set(scopes))
    if not scopes or not set(scopes) <= SCOPES:
        raise ValueError(f"scopes must be a non-empty subset of {sorted(SCOPES)}")
    if not 1 <= ttl_seconds <= MAX_TTL:
        raise ValueError(f"ttl must be 1..{MAX_TTL} seconds")
    if not _SUB.match(sub or ""):
        raise ValueError("sub must be 1-64 characters of A-Z a-z 0-9 _ @ -")
    jti = jti or secrets.token_hex(8)
    exp = int((now if now is not None else time.time()) + ttl_seconds)
    body = f"v2.{sub}.{'+'.join(scopes)}.{exp}.{jti}"
    return f"{body}.{_sig(secret, body)}"


def verify(secret: bytes, token: str, now=None):
    """Return {sub, scopes:set, exp:int, jti} or raise AuthError. Revocation is checked by the caller."""
    parts = (token or "").split(".")
    if len(parts) != 6 or parts[0] != "v2":
        raise AuthError("AUTH_INVALID", "Malformed credential")
    _, sub, scope_s, exp_s, jti, sig = parts
    body = f"v2.{sub}.{scope_s}.{exp_s}.{jti}"
    if not hmac.compare_digest(sig, _sig(secret, body)):
        raise AuthError("AUTH_INVALID", "Invalid credential")
    try:
        exp = int(exp_s)
    except ValueError:
        raise AuthError("AUTH_INVALID", "Malformed credential")
    if (now if now is not None else time.time()) >= exp:
        raise AuthError("AUTH_EXPIRED", "Credential expired")
    scopes = set(scope_s.split("+"))
    if not scopes <= SCOPES or not _SUB.match(sub):
        raise AuthError("AUTH_INVALID", "Invalid credential")
    return {"sub": sub, "scopes": scopes, "exp": exp, "jti": jti}


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
    ap.add_argument("--sub", default="local", help="accountable identity recorded on approvals")
    ap.add_argument("--revoke", default=None, metavar="JTI", help="revoke the token with this id instead of minting")
    a = ap.parse_args()
    if a.revoke:
        from engine.storage import Store, derive_audit_key

        d = Path(a.data or Path(__file__).resolve().parents[1] / "data")
        Store(d / "planreview.sqlite", key=derive_audit_key(load_secret(a.data))).revoke(a.revoke, "cli")
        print(f"revoked {a.revoke}")
    else:
        print(mint(load_secret(a.data), a.scopes.split(","), _parse_ttl(a.ttl), sub=a.sub))
