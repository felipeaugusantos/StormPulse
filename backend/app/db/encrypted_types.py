"""SQLAlchemy column type that transparently AES-GCM encrypts/decrypts a
string field (see `app.core.crypto`, ADR-0055). The ORM attribute always
reads and writes plaintext — only the value actually sent to/read from
Postgres is ciphertext, so every existing call site that constructs a
`User(...)`, reads `user.email`, etc. keeps working unchanged."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt_field, encrypt_field


class EncryptedString(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return encrypt_field(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt_field(value)
