from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.enums import UserRole
from app.organizations.models import OrganizationInvitation
from app.organizations.permissions import can_manage_members, can_write, membership_active
from app.organizations.schemas import InvitationCreateIn, MemberUpdateIn
from app.organizations.service import invitation_usable
from app.users.models import User
from workers.email import render_email


def _user(role: UserRole, *, expires_at: datetime | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="member@example.com",
        email_index="x" * 64,
        hashed_password="hash",
        role=role,
        is_active=True,
        access_expires_at=expires_at,
    )


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.ADMIN, UserRole.USER])
def test_only_management_roles_administer_members(role: UserRole) -> None:
    assert can_manage_members(_user(role))


@pytest.mark.parametrize("role", [UserRole.AGRONOMIST, UserRole.OPERATOR, UserRole.VIEWER])
def test_operational_roles_never_administer_members(role: UserRole) -> None:
    assert not can_manage_members(_user(role))


def test_viewer_is_read_only_but_operator_and_agronomist_can_write() -> None:
    assert not can_write(_user(UserRole.VIEWER))
    assert can_write(_user(UserRole.OPERATOR))
    assert can_write(_user(UserRole.AGRONOMIST))


def test_temporary_membership_expires_immediately() -> None:
    assert membership_active(
        _user(UserRole.VIEWER, expires_at=datetime.now(UTC) + timedelta(seconds=1))
    )
    assert not membership_active(
        _user(UserRole.VIEWER, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )


def test_owner_cannot_be_invited_or_assigned() -> None:
    with pytest.raises(ValidationError):
        InvitationCreateIn(email="owner@example.com", role=UserRole.OWNER)
    with pytest.raises(ValidationError):
        MemberUpdateIn(role=UserRole.OWNER)


def test_invitation_email_explains_expiry_and_single_use() -> None:
    content = render_email("organization_invitation", link="https://example.test/invite")
    assert "expira" in content.text_body
    assert "uma vez" in content.text_body


def test_expired_used_and_revoked_invitations_are_rejected() -> None:
    now = datetime.now(UTC)
    base = {
        "tenant_id": uuid.uuid4(),
        "email": "invite@example.com",
        "email_index": "x" * 64,
        "role": "viewer",
        "token_hash": "y" * 64,
        "invited_by_user_id": uuid.uuid4(),
    }
    assert not invitation_usable(
        OrganizationInvitation(**base, expires_at=now - timedelta(seconds=1)), now
    )
    assert not invitation_usable(
        OrganizationInvitation(**base, expires_at=now + timedelta(hours=1), accepted_at=now), now
    )
    assert not invitation_usable(
        OrganizationInvitation(**base, expires_at=now + timedelta(hours=1), revoked_at=now), now
    )
