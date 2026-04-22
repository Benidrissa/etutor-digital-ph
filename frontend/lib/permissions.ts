export type OrgRole = "owner" | "admin" | "viewer" | null;

/**
 * Returns true when the user may create or edit question banks in an org.
 *
 * Allowed:
 * - Platform admin or sub_admin (always, regardless of org role).
 * - Platform expert who is any org member.
 * - Org owner or admin (any platform role).
 */
export function canEditBank(
  orgRole: OrgRole,
  platformRole: string | undefined,
): boolean {
  if (platformRole === "admin" || platformRole === "sub_admin") return true;
  if (!orgRole) return false;
  if (platformRole === "expert") return true;
  return orgRole === "owner" || orgRole === "admin";
}
