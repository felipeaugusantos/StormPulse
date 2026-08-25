"""Tests for field-level encryption at rest (ADR-0055)."""

from __future__ import annotations

from app.core.crypto import blind_index, decrypt_field, encrypt_field


def test_encrypt_then_decrypt_round_trips() -> None:
    plaintext = "user@example.com"
    ciphertext = encrypt_field(plaintext)
    assert ciphertext != plaintext
    assert decrypt_field(ciphertext) == plaintext


def test_encrypting_the_same_value_twice_yields_different_ciphertext() -> None:
    # Random nonce per call (AES-GCM) — this is exactly why equality lookups
    # and uniqueness can't run against the encrypted column itself; see
    # blind_index below.
    a = encrypt_field("user@example.com")
    b = encrypt_field("user@example.com")
    assert a != b
    assert decrypt_field(a) == decrypt_field(b) == "user@example.com"


def test_blind_index_is_deterministic() -> None:
    assert blind_index("user@example.com") == blind_index("user@example.com")


def test_blind_index_differs_for_different_values() -> None:
    assert blind_index("a@example.com") != blind_index("b@example.com")


def test_blind_index_does_not_reveal_the_plaintext() -> None:
    assert "user" not in blind_index("user@example.com")
    assert "example.com" not in blind_index("user@example.com")
