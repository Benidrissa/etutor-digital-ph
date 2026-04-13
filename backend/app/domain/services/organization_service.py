"""Organization service — CRUD, member management, credit account."""

from __future__ import annotations

import re
import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.credit import CreditAccount
from app.domain.models.organization import Organization, OrganizationMember, OrgMemberRole
from app.domain.models.user import User, UserRole
from app.domain.models.user_group import UserGroup, UserGroupMember

logger = structlog.get_logger(__name__)


def _slugify(name: str) -> str:
    """Convert name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


class OrganizationService:
    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_organization(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        contact_email: str | None = None,
        logo_url: str | None = None,
        creator_id: uuid.UUID,
    ) -> Organization:
        """Create an organization with the caller as owner.

        Auto-creates a UserGroup and CreditAccount for the org.
        """
        creator = await db.get(User, creator_id)
        if creator is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        final_slug = slug or _slugify(name)

        # Check slug uniqueness
        existing = await db.execute(select(Organization).where(Organization.slug == final_slug))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Slug '{final_slug}' already in use.",
            )

        # Auto-create UserGroup
        group = UserGroup(name=f"org:{final_slug}", created_by=creator_id)
        db.add(group)
        await db.flush()

        # Add creator to the group
        db.add(UserGroupMember(group_id=group.id, user_id=creator_id))

        # Auto-create CreditAccount
        credit_account = CreditAccount(organization_id=None)  # set after org creation
        db.add(credit_account)
        await db.flush()

        org = Organization(
            name=name,
            slug=final_slug,
            description=description,
            contact_email=contact_email,
            logo_url=logo_url,
            credit_account_id=credit_account.id,
            user_group_id=group.id,
        )
        db.add(org)
        await db.flush()

        # Back-link credit account to org
        credit_account.organization_id = org.id

        # Add creator as owner
        db.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=creator_id,
                role=OrgMemberRole.owner,
                invited_by=None,
            )
        )
        await db.commit()
        await db.refresh(org)
        logger.info("organization_created", org_id=str(org.id), slug=org.slug)
        return org

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_organization(self, db: AsyncSession, org_id: uuid.UUID) -> Organization:
        org = await db.get(Organization, org_id)
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
            )
        return org

    async def get_organization_by_slug(self, db: AsyncSession, slug: str) -> Organization:
        result = await db.execute(select(Organization).where(Organization.slug == slug))
        org = result.scalar_one_or_none()
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
            )
        return org

    async def list_user_organizations(self, db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
        """Return all organizations where the user is a member, with their role."""
        result = await db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .options(selectinload(OrganizationMember.organization))
        )
        memberships = result.scalars().all()
        return [
            {
                "organization": m.organization,
                "role": m.role,
                "joined_at": m.joined_at,
            }
            for m in memberships
        ]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_organization(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields: str | None,
    ) -> Organization:
        """Update org fields. Only owner/admin can update."""
        await self.require_org_role(db, org_id, actor_id, OrgMemberRole.owner, OrgMemberRole.admin)
        org = await self.get_organization(db, org_id)

        allowed = {"name", "description", "contact_email", "logo_url"}
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(org, key, value)

        await db.commit()
        await db.refresh(org)
        return org

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------

    async def add_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_email: str,
        role: OrgMemberRole,
        invited_by: uuid.UUID,
    ) -> OrganizationMember:
        """Add a user to the org by email. Requires owner/admin."""
        await self.require_org_role(
            db, org_id, invited_by, OrgMemberRole.owner, OrgMemberRole.admin
        )

        # Find user by email
        result = await db.execute(select(User).where(User.email == user_email))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user found with email {user_email}.",
            )

        # Check not already a member
        existing = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this organization.",
            )

        member = OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role=role,
            invited_by=invited_by,
        )
        db.add(member)

        # Also add to org's user group
        org = await self.get_organization(db, org_id)
        if org.user_group_id:
            existing_gm = await db.execute(
                select(UserGroupMember).where(
                    UserGroupMember.group_id == org.user_group_id,
                    UserGroupMember.user_id == user.id,
                )
            )
            if not existing_gm.scalar_one_or_none():
                db.add(UserGroupMember(group_id=org.user_group_id, user_id=user.id))

        await db.commit()
        await db.refresh(member)
        logger.info(
            "org_member_added",
            org_id=str(org_id),
            user_id=str(user.id),
            role=role.value,
        )
        return member

    async def remove_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Remove a member. Owners can remove anyone except the last owner."""
        await self.require_org_role(db, org_id, actor_id, OrgMemberRole.owner, OrgMemberRole.admin)

        member_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
        member = member_result.scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

        # Prevent removing the last owner
        if member.role == OrgMemberRole.owner:
            owners_result = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.role == OrgMemberRole.owner,
                )
            )
            owners = owners_result.scalars().all()
            if len(owners) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last owner.",
                )

        await db.delete(member)

        # Also remove from org's user group
        org = await self.get_organization(db, org_id)
        if org.user_group_id:
            gm_result = await db.execute(
                select(UserGroupMember).where(
                    UserGroupMember.group_id == org.user_group_id,
                    UserGroupMember.user_id == target_user_id,
                )
            )
            gm = gm_result.scalar_one_or_none()
            if gm:
                await db.delete(gm)

        await db.commit()
        logger.info(
            "org_member_removed",
            org_id=str(org_id),
            user_id=str(target_user_id),
        )

    async def update_member_role(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: OrgMemberRole,
        actor_id: uuid.UUID,
    ) -> OrganizationMember:
        """Change a member's role. Only owners can change roles."""
        await self.require_org_role(db, org_id, actor_id, OrgMemberRole.owner)

        member_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
        member = member_result.scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

        # Prevent demoting the last owner
        if member.role == OrgMemberRole.owner and new_role != OrgMemberRole.owner:
            owners_result = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.role == OrgMemberRole.owner,
                )
            )
            owners = owners_result.scalars().all()
            if len(owners) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot demote the last owner.",
                )

        member.role = new_role
        await db.commit()
        await db.refresh(member)
        return member

    async def list_members(self, db: AsyncSession, org_id: uuid.UUID) -> list[OrganizationMember]:
        result = await db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == org_id)
            .options(selectinload(OrganizationMember.user))
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Credits
    # ------------------------------------------------------------------

    async def get_org_credit_balance(self, db: AsyncSession, org_id: uuid.UUID) -> int:
        org = await self.get_organization(db, org_id)
        if org.credit_account_id is None:
            return 0
        account = await db.get(CreditAccount, org.credit_account_id)
        return account.balance if account else 0

    # ------------------------------------------------------------------
    # Authorization guard
    # ------------------------------------------------------------------

    async def require_org_role(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        *allowed_roles: OrgMemberRole,
    ) -> OrganizationMember:
        """Verify user is a member with one of the allowed roles. Raises 403 otherwise.

        Platform admins bypass the check.
        """
        user = await db.get(User, user_id)
        if user and user.role == UserRole.admin:
            # Platform admin — create a synthetic membership for convenience
            member_result = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == user_id,
                )
            )
            member = member_result.scalar_one_or_none()
            if member:
                return member
            # Admin not a member — still allow but return a transient object
            return OrganizationMember(
                organization_id=org_id,
                user_id=user_id,
                role=OrgMemberRole.owner,
            )

        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization.",
            )
        if allowed_roles and member.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(r.value for r in allowed_roles)}.",
            )
        return member
