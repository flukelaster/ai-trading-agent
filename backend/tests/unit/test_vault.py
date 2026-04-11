"""Unit tests for VaultService (AES-256-GCM + HKDF)."""

import pytest

from app.vault import VaultService, VaultUnavailableError


class TestVaultService:
    def test_encrypt_decrypt_roundtrip(self):
        svc = VaultService("test-master-key-123")
        plaintext = "sk-ant-oat01-abc123def456"
        ciphertext, nonce = svc.encrypt(plaintext)
        result = svc.decrypt(ciphertext, nonce)
        assert result == plaintext

    def test_encrypt_different_nonces(self):
        svc = VaultService("test-key")
        _, nonce1 = svc.encrypt("value")
        _, nonce2 = svc.encrypt("value")
        assert nonce1 != nonce2  # nonces must be unique

    def test_hkdf_deterministic(self):
        svc1 = VaultService("same-key")
        svc2 = VaultService("same-key")
        # Same key should produce same derived key
        plaintext = "test-value"
        ct1, n1 = svc1.encrypt(plaintext)
        # svc2 should be able to decrypt what svc1 encrypted
        assert svc2.decrypt(ct1, n1) == plaintext

    def test_different_keys_cannot_decrypt(self):
        svc1 = VaultService("key-one")
        svc2 = VaultService("key-two")
        ct, nonce = svc1.encrypt("secret")
        with pytest.raises(Exception):
            svc2.decrypt(ct, nonce)

    def test_vault_unavailable_no_key(self):
        svc = VaultService(None)
        assert not svc.is_available
        with pytest.raises(VaultUnavailableError):
            svc.encrypt("test")
        with pytest.raises(VaultUnavailableError):
            svc.decrypt(b"ct", b"nonce")

    def test_vault_available_with_key(self):
        svc = VaultService("any-key")
        assert svc.is_available

    def test_empty_string_key_unavailable(self):
        svc = VaultService("")
        assert not svc.is_available


class TestMaskValue:
    def test_long_value(self):
        result = VaultService.mask_value("sk-ant-oat01-abc123def456fa61")
        assert result == "sk-ant***fa61"
        assert "abc123" not in result

    def test_medium_value(self):
        result = VaultService.mask_value("abcdefgh")
        assert result == "***gh"  # len 8 <= 8, so short format

    def test_short_value(self):
        result = VaultService.mask_value("short")
        assert result == "***rt"

    def test_very_short_value(self):
        result = VaultService.mask_value("ab")
        assert result == "***"

    def test_four_chars(self):
        result = VaultService.mask_value("abcd")
        assert result == "***"

    def test_five_chars(self):
        result = VaultService.mask_value("abcde")
        assert result == "***de"
