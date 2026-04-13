"""Tests for OrganizationService — CRUD, member management, credit account."""

import uuid

import pytest
from fastapi import HTTPException

from app.domain.models.organization import OrgMemberRole
from app.domain.models.user import User, UserRole
from app.domain.services.organization_service import OrganizationService


@pytest.fixture
async def org_svc():
    return OrganizationService()


@pytest.fixture
async def test_user(db_session):
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        email="org-creator@test.com",
        name="Org Creator",
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_user2(db_session):
    """Create a second test user."""
    user = User(
        id=uuid.uuid4(),
        email="member@test.com",
        name="Test Member",
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session):
    """Create a platform admin user."""
    user = User(
        id=uuid.uuid4(),
        email="admin@test.com",
        name="Admin User",
        role=UserRole.admin,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_create_organization(db_session, org_svc, test_user):
    """Creating an org should auto-create UserGroup + CreditAccount and add creator as owner."""
    org = await org_svc.create_organization(
        db_session,
        name="Test NGO",
        slug="test-ngo",
        contact_email="ngo@test.com",
        creator_id=test_user.id,
    )

    assert org.name == "Test NGO"
    assert org.slug == "test-ngo"
    assert org.credit_account_id is not None
    assert org.user_group_id is not None
    assert org.is_active is True

    # Verify creator is owner
    members = await org_svc.list_members(db_session, org.id)
    assert len(members) == 1
    assert members[0].user_id == test_user.id
    assert members[0].role == OrgMemberRole.owner


@pytest.mark.asyncio
async def test_create_duplicate_slug_fails(db_session, org_svc, test_user):
    """Creating two orgs with the same slug should fail."""
    await org_svc.create_organization(
        db_session, name="First", slug="my-org", creator_id=test_user.id
    )
    with pytest.raises(HTTPException) as exc_info:
        await org_svc.create_organization(
            db_session, name="Second", slug="my-org", creator_id=test_user.id
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_add_member(db_session, org_svc, test_user, test_user2):
    """Adding a member by email should work."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo", creator_id=test_user.id
    )

    member = await org_svc.add_member(
        db_session,
        org_id=org.id,
        user_email="member@test.com",
        role=OrgMemberRole.viewer,
        invited_by=test_user.id,
    )
    assert member.user_id == test_user2.id
    assert member.role == OrgMemberRole.viewer


@pytest.mark.asyncio
async def test_add_duplicate_member_fails(db_session, org_svc, test_user, test_user2):
    """Adding the same user twice should fail."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo2", creator_id=test_user.id
    )
    await org_svc.add_member(
        db_session, org.id, "member@test.com", OrgMemberRole.viewer, test_user.id
    )
    with pytest.raises(HTTPException) as exc_info:
        await org_svc.add_member(
            db_session, org.id, "member@test.com", OrgMemberRole.viewer, test_user.id
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_last_owner_fails(db_session, org_svc, test_user):
    """Removing the last owner should fail."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo3", creator_id=test_user.id
    )
    with pytest.raises(HTTPException) as exc_info:
        await org_svc.remove_member(db_session, org.id, test_user.id, test_user.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_member_role(db_session, org_svc, test_user, test_user2):
    """Updating a member's role should work."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo4", creator_id=test_user.id
    )
    await org_svc.add_member(
        db_session, org.id, "member@test.com", OrgMemberRole.viewer, test_user.id
    )
    updated = await org_svc.update_member_role(
        db_session, org.id, test_user2.id, OrgMemberRole.admin, test_user.id
    )
    assert updated.role == OrgMemberRole.admin


@pytest.mark.asyncio
async def test_require_org_role_non_member_fails(db_session, org_svc, test_user, test_user2):
    """Non-member should be denied access."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo5", creator_id=test_user.id
    )
    with pytest.raises(HTTPException) as exc_info:
        await org_svc.require_org_role(db_session, org.id, test_user2.id, OrgMemberRole.owner)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_bypasses_role_check(db_session, org_svc, test_user, admin_user):
    """Platform admin should bypass org role checks."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo6", creator_id=test_user.id
    )
    # Admin not a member but should still pass
    member = await org_svc.require_org_role(db_session, org.id, admin_user.id, OrgMemberRole.owner)
    assert member.role == OrgMemberRole.owner


@pytest.mark.asyncio
async def test_get_org_credit_balance(db_session, org_svc, test_user):
    """Org credit balance should start at 0."""
    org = await org_svc.create_organization(
        db_session, name="NGO", slug="ngo7", creator_id=test_user.id
    )
    balance = await org_svc.get_org_credit_balance(db_session, org.id)
    assert balance == 0
