"""Encryption at rest for plan evidence (Fernet: AES-128-CBC + HMAC-SHA256).

Sealed: the saved Terraform plan (`*.tfplan`), the raw plan JSON, and the raw plan copy inside the
audit log. Plaintext exists only while a step needs it: the raw JSON is read in memory, and the saved
plan is restored to disk only for the duration of an apply, then deleted.

NOT sealed: `terraform.tfstate` and `main.tf` -- Terraform must read them in place for every command.
Keep the data directory on an encrypted volume (BitLocker/FileVault/LUKS) for those.

The key is derived from the API secret. Keep the secret in PLANREVIEW_API_SECRET (environment) rather
than the generated `data/api_secret` file, otherwise the key sits next to the ciphertext and this only
protects against casual disclosure (backups, cloud sync of the data folder), not against a reader of
the data directory. See docs/threat-model.md.
"""

import base64
import contextlib
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SUFFIX = ".enc"


def derive_key(secret: bytes) -> bytes:
    return base64.urlsafe_b64encode(hmac.new(secret, b"planreview-artifact-key-v1", hashlib.sha256).digest())


def enabled_by_env():
    return os.environ.get("PLANREVIEW_ENCRYPT_AT_REST", "1") != "0"


class Vault:
    def __init__(self, secret: bytes | None, enabled=None):
        self.enabled = enabled_by_env() if enabled is None else enabled
        self._f = Fernet(derive_key(secret)) if (secret and self.enabled) else None
        self.enabled = self._f is not None

    # ------------------------------------------------------------ text
    def encrypt_text(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode()

    def decrypt_text(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            raise ValueError("sealed evidence cannot be decrypted (wrong secret or tampered data)")

    # ----------------------------------------------------------- files
    @staticmethod
    def _enc(path):
        p = Path(path)
        return p.with_name(p.name + SUFFIX)

    def exists(self, path) -> bool:
        return Path(path).exists() or self._enc(path).exists()

    def read_bytes(self, path) -> bytes:
        p = Path(path)
        if p.exists():
            return p.read_bytes()
        e = self._enc(path)
        if not e.exists() or self._f is None:
            raise FileNotFoundError(str(path))
        try:
            return self._f.decrypt(e.read_bytes())
        except InvalidToken:
            raise ValueError("sealed evidence cannot be decrypted (wrong secret or tampered data)")

    def read_text(self, path, encoding="utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def digest(self, path) -> str:
        """SHA-256 of the PLAINTEXT, whether the file is sealed or not."""
        return hashlib.sha256(self.read_bytes(path)).hexdigest()

    def seal(self, path):
        """Replace `path` with `path.enc`. No-op when disabled."""
        if not self.enabled:
            return
        p, e = Path(path), self._enc(path)
        tmp = e.with_name(e.name + ".tmp")
        tmp.write_bytes(self._f.encrypt(p.read_bytes()))
        os.replace(tmp, e)
        p.unlink()

    @contextlib.contextmanager
    def unsealed(self, path):
        """Restore the plaintext at `path` for the duration of the block, then delete it again."""
        p = Path(path)
        restored = False
        if not p.exists() and self._enc(path).exists() and self._f is not None:
            p.write_bytes(self.read_bytes(path))
            restored = True
        try:
            yield p
        finally:
            if restored and p.exists():
                p.unlink()
