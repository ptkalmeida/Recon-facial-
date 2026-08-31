"""Criptografia em repouso dos embeddings faciais."""

import pytest

from app.security import crypto
from app.security.crypto import EmbeddingCipher, EmbeddingCipherError

EMBEDDING = [0.125, -0.5, 0.0, 0.999]


@pytest.fixture
def cipher(tmp_path, monkeypatch):
    """Cifra com chave real e salt isolado no tmp_path."""
    monkeypatch.setattr(crypto, "_salt_path", lambda: tmp_path / "embedding_salt.key")
    # PBKDF2 real com 480k iterações é lento demais para teste unitário.
    monkeypatch.setattr(crypto, "PBKDF2_ITERATIONS", 1_000)
    return EmbeddingCipher(key_material="chave-de-teste-com-16+")


def test_roundtrip_preserves_embedding(cipher):
    assert cipher.enabled
    stored = cipher.encrypt(EMBEDDING)

    assert isinstance(stored, dict) and stored["v"] == 1
    assert cipher.decrypt(stored) == EMBEDDING


def test_ciphertext_does_not_leak_the_values(cipher):
    stored = cipher.encrypt(EMBEDDING)

    assert "0.125" not in stored["enc"]
    assert "0.999" not in stored["enc"]


def test_reads_legacy_plaintext_rows(cipher):
    """Bancos criados antes da criptografia continuam legíveis."""
    assert cipher.decrypt(EMBEDDING) == EMBEDDING


def test_disabled_without_key_stores_plaintext():
    disabled = EmbeddingCipher(key_material="")

    assert not disabled.enabled
    assert disabled.encrypt(EMBEDDING) == EMBEDDING
    assert disabled.decrypt(EMBEDDING) == EMBEDDING


def test_disabled_cipher_cannot_read_encrypted_rows(cipher):
    stored = cipher.encrypt(EMBEDDING)
    disabled = EmbeddingCipher(key_material="")

    with pytest.raises(EmbeddingCipherError, match="não está definida"):
        disabled.decrypt(stored)


def test_wrong_key_is_rejected_not_silently_wrong(cipher, tmp_path, monkeypatch):
    stored = cipher.encrypt(EMBEDDING)
    other = EmbeddingCipher(key_material="outra-chave-diferente")

    with pytest.raises(EmbeddingCipherError, match="descriptografar"):
        other.decrypt(stored)
