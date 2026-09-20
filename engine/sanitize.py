"""Scrub text before it leaves the server: absolute paths, tokens, control characters."""

import re

_SEG = r"[^\s\"'<>|:*?]"
_WIN = re.compile(r"[A-Za-z]:[\\/](?:" + _SEG + r"+[\\/])*" + _SEG + r"*")
_POSIX = re.compile(r"(?<![\w.])/(?:[\w.\-@+ ]+/)+[\w.\-@+]*")
_TOKEN = re.compile(r"\bv1\.[A-Za-z0-9+_,\-]+\.\d+\.[A-Za-z0-9_\-]{20,}")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")


def scrub(text, limit=500):
    """Return `text` safe for an API response: no absolute paths or credentials."""
    s = str(text)
    s = _TOKEN.sub("<token>", s)
    s = _BEARER.sub("Bearer <token>", s)
    s = _WIN.sub("<path>", s)
    s = _POSIX.sub("<path>", s)
    s = "".join(ch if ch >= " " or ch in "\n\t" else " " for ch in s)
    return s if len(s) <= limit else s[:limit] + "…"
