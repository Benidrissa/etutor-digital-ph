"""Tests for OrganizationService — import and instantiation."""

from app.domain.models.organization import Organization, OrganizationMember, OrgMemberRole
from app.domain.services.organization_service import OrganizationService


def test_organization_service_instantiation():
    """Service can be instantiated without errors."""
    svc = OrganizationService()
    assert svc is not None


def test_org_member_role_values():
    """OrgMemberRole enum has expected values."""
    assert OrgMemberRole.owner == "owner"
    assert OrgMemberRole.admin == "admin"
    assert OrgMemberRole.viewer == "viewer"


def test_organization_model_has_expected_columns():
    """Organization model has the columns we expect."""
    columns = {c.key for c in Organization.__table__.columns}
    assert "id" in columns
    assert "name" in columns
    assert "slug" in columns
    assert "credit_account_id" in columns
    assert "user_group_id" in columns
    assert "is_active" in columns


def test_organization_member_model_has_expected_columns():
    """OrganizationMember model has the columns we expect."""
    columns = {c.key for c in OrganizationMember.__table__.columns}
    assert "organization_id" in columns
    assert "user_id" in columns
    assert "role" in columns
    assert "invited_by" in columns
