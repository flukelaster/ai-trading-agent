"""
Secrets Vault — AES-256-GCM encryption with HKDF key derivation.

Master key is stored only in VAULT_MASTER_KEY env var (Railway).
Never passes through API or UI.
"""

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException


class VaultUnavailableError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=503,
            detail="Vault unavailable — VAULT_MASTER_KEY not configured",
        )


class VaultService:
    """AES-256-GCM encryption service with HKDF key derivation."""

    _SALT = b"gold-trading-bot-vault-v1"
    _INFO = b"secrets-encryption"

    def __init__(self, master_key: str | None):
        self._derived_key: bytes | None = None
        if master_key:
            self._derived_key = self._derive_key(master_key)

    def _derive_key(self, master_key: str) -> bytes:
        """HKDF-SHA256: derive a 32-byte AES key from the master key."""
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._SALT,
            info=self._INFO,
        ).derive(master_key.encode())

    def _require_key(self):
        if not self._derived_key:
            raise VaultUnavailableError()

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Encrypt plaintext. Returns (ciphertext, nonce)."""
        self._require_key()
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._derived_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """Decrypt ciphertext. Returns plaintext string."""
        self._require_key()
        aesgcm = AESGCM(self._derived_key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode()

    @staticmethod
    def mask_value(plaintext: str) -> str:
        """Mask a secret value for display.

        Examples:
            'sk-ant-oat01-abc123def456fa61' -> 'sk-ant***fa61'
            'short' -> '***rt'
            'ab' -> '***'
        """
        if len(plaintext) <= 4:
            return "***"
        if len(plaintext) <= 8:
            return "***" + plaintext[-2:]
        return plaintext[:6] + "***" + plaintext[-4:]

    @property
    def is_available(self) -> bool:
        return self._derived_key is not None


# Module-level singleton
from app.config import settings  # noqa: E402

vault = VaultService(settings.vault_master_key or None)
