"""encrypt user PII at rest

Revision ID: ab4b31a9059a
Revises: 0b7b9a5dbd11
Create Date: 2026-08-25 13:49:22.824838

Encrypts `users.email`, `users.full_name`, `users.google_sub`, and the
`admin_audit_log.actor_email`/`target_email` snapshots with AES-256-GCM at
rest (ADR-0055, `app.core.crypto`). Since AES-GCM uses a random nonce per
value, the encrypted `email`/`google_sub` columns can never satisfy the
existing unique constraints or equality lookups (`login`, `_email_exists`,
Google-sub linking, the admin-search filter) — two rows with the identical
plaintext now have different ciphertext. `email_index`/`google_sub_index`
(deterministic HMAC-SHA256) become the columns uniqueness and lookups
actually run against; `app.core.crypto.blind_index` is the only thing that
can compute one, and doing so requires knowing the plaintext already, so a
leaked index value proves two rows share a value without revealing it.

**Guarded for two very different starting states.** A fresh database
(CI, or any brand-new install) gets its schema from `0001_bootstrap`'s
`Base.metadata.create_all()` against the *current* models — which, as of
this migration, already declare `email`/`full_name`/`google_sub` as
`EncryptedString` (backed by `Text`) and already include `email_index`/
`google_sub_index`. Re-running this migration's `ALTER`/`ADD COLUMN`
statements unconditionally against that schema would fail outright
(`DuplicateColumn`) — the exact failure mode already documented in
`5e36b6016c06_add_users_google_sub.py`. Every structural change here is
gated on inspecting the live column type/existing columns/indexes first,
same idiom as that migration. The data backfill itself is separately safe
to re-run on either schema: it only touches rows with `email_index IS
NULL`, which is empty on a freshly-bootstrapped table and exactly the set
of not-yet-encrypted rows on an existing (pre-this-migration) production
database.

Requires `Settings.field_encryption_key`/`field_encryption_index_key` to
already be the real production values in this deployment's `.env` *before*
this migration runs — same operational requirement, and same production
startup gate (`Settings`'s `_forbid_dev_secret_in_production` validator),
as `POSTGRES_APP_PASSWORD` needed for migration `0b7b9a5dbd11`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab4b31a9059a"
down_revision: str | None = "0b7b9a5dbd11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_varchar(column_info: object) -> bool:
    return "VARCHAR" in str(column_info["type"]).upper()  # type: ignore[index]


def upgrade() -> None:
    from app.core.crypto import blind_index, encrypt_field

    conn = op.get_bind()
    inspector = sa.inspect(conn)

    users_columns = {c["name"]: c for c in inspector.get_columns("users")}
    if _is_varchar(users_columns["email"]):
        op.execute("ALTER TABLE users ALTER COLUMN email TYPE text")
        op.execute("ALTER TABLE users ALTER COLUMN full_name TYPE text")
        op.execute("ALTER TABLE users ALTER COLUMN google_sub TYPE text")

    users_columns = {c["name"]: c for c in inspector.get_columns("users")}
    if "email_index" not in users_columns:
        op.add_column("users", sa.Column("email_index", sa.String(length=64), nullable=True))
    if "google_sub_index" not in users_columns:
        op.add_column("users", sa.Column("google_sub_index", sa.String(length=64), nullable=True))

    rows = conn.execute(
        sa.text("SELECT id, email, full_name, google_sub FROM users WHERE email_index IS NULL")
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET email = :email, email_index = :email_index, "
                "full_name = :full_name, google_sub = :google_sub, "
                "google_sub_index = :google_sub_index WHERE id = :id"
            ),
            {
                "email": encrypt_field(row.email),
                "email_index": blind_index(row.email),
                "full_name": encrypt_field(row.full_name) if row.full_name is not None else None,
                "google_sub": encrypt_field(row.google_sub) if row.google_sub is not None else None,
                "google_sub_index": blind_index(row.google_sub)
                if row.google_sub is not None
                else None,
                "id": row.id,
            },
        )

    op.execute("ALTER TABLE users ALTER COLUMN email_index SET NOT NULL")

    existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
    if "ix_users_email" in existing_indexes:
        op.drop_index("ix_users_email", table_name="users")
    if "ix_users_google_sub" in existing_indexes:
        op.drop_index("ix_users_google_sub", table_name="users")
    existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
    if "ix_users_email_index" not in existing_indexes:
        op.create_index("ix_users_email_index", "users", ["email_index"], unique=True)
    if "ix_users_google_sub_index" not in existing_indexes:
        op.create_index("ix_users_google_sub_index", "users", ["google_sub_index"], unique=True)

    audit_columns = {c["name"]: c for c in inspector.get_columns("admin_audit_log")}
    if _is_varchar(audit_columns["actor_email"]):
        op.execute("ALTER TABLE admin_audit_log ALTER COLUMN actor_email TYPE text")
        op.execute("ALTER TABLE admin_audit_log ALTER COLUMN target_email TYPE text")
        audit_rows = conn.execute(
            sa.text("SELECT id, actor_email, target_email FROM admin_audit_log")
        ).fetchall()
        for row in audit_rows:
            conn.execute(
                sa.text(
                    "UPDATE admin_audit_log SET actor_email = :actor_email, "
                    "target_email = :target_email WHERE id = :id"
                ),
                {
                    "actor_email": encrypt_field(row.actor_email),
                    "target_email": encrypt_field(row.target_email)
                    if row.target_email is not None
                    else None,
                    "id": row.id,
                },
            )


def downgrade() -> None:
    from app.core.crypto import decrypt_field

    conn = op.get_bind()

    rows = conn.execute(sa.text("SELECT id, email, full_name, google_sub FROM users")).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET email = :email, full_name = :full_name, "
                "google_sub = :google_sub WHERE id = :id"
            ),
            {
                "email": decrypt_field(row.email),
                "full_name": decrypt_field(row.full_name) if row.full_name is not None else None,
                "google_sub": decrypt_field(row.google_sub) if row.google_sub is not None else None,
                "id": row.id,
            },
        )

    op.execute("ALTER TABLE users ALTER COLUMN email TYPE varchar(255) USING email::varchar(255)")
    op.execute(
        "ALTER TABLE users ALTER COLUMN full_name TYPE varchar(120) USING full_name::varchar(120)"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN google_sub TYPE varchar(255) USING google_sub::varchar(255)"
    )

    inspector = sa.inspect(conn)
    existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
    if "ix_users_email_index" in existing_indexes:
        op.drop_index("ix_users_email_index", table_name="users")
    if "ix_users_google_sub_index" in existing_indexes:
        op.drop_index("ix_users_google_sub_index", table_name="users")
    op.drop_column("users", "email_index")
    op.drop_column("users", "google_sub_index")

    existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
    if "ix_users_email" not in existing_indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    if "ix_users_google_sub" not in existing_indexes:
        op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    audit_rows = conn.execute(
        sa.text("SELECT id, actor_email, target_email FROM admin_audit_log")
    ).fetchall()
    for row in audit_rows:
        conn.execute(
            sa.text(
                "UPDATE admin_audit_log SET actor_email = :actor_email, "
                "target_email = :target_email WHERE id = :id"
            ),
            {
                "actor_email": decrypt_field(row.actor_email),
                "target_email": decrypt_field(row.target_email)
                if row.target_email is not None
                else None,
                "id": row.id,
            },
        )
    op.execute(
        "ALTER TABLE admin_audit_log ALTER COLUMN actor_email TYPE varchar(255) "
        "USING actor_email::varchar(255)"
    )
    op.execute(
        "ALTER TABLE admin_audit_log ALTER COLUMN target_email TYPE varchar(255) "
        "USING target_email::varchar(255)"
    )
