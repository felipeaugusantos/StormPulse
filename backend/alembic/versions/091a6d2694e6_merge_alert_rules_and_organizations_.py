"""merge alert_rules and organizations migration heads

Revision ID: 091a6d2694e6
Revises: 7e8060f3f148, a4c8e1f7b2d5
Create Date: 2026-09-07 14:32:16.342275
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "091a6d2694e6"
down_revision: str | None = ("7e8060f3f148", "a4c8e1f7b2d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
