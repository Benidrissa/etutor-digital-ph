"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import { fetchOrgMembers, addOrgMember, removeOrgMember } from "@/lib/api";
import type { OrgMember } from "@/lib/api";
import { UserPlus, Trash2 } from "lucide-react";

export default function OrgMembersPage() {
  const t = useTranslations("Organization");
  const { orgId, role } = useOrg();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [email, setEmail] = useState("");
  const [memberRole, setMemberRole] = useState("viewer");
  const [adding, setAdding] = useState(false);

  const canManage = role === "owner" || role === "admin";

  useEffect(() => {
    if (!orgId) return;
    fetchOrgMembers(orgId).then(setMembers).catch(() => {});
  }, [orgId]);

  const handleAdd = async () => {
    if (!orgId || !email) return;
    setAdding(true);
    try {
      const member = await addOrgMember(orgId, email, memberRole);
      setMembers((prev) => [...prev, member]);
      setEmail("");
      setShowForm(false);
    } catch (err) {
      console.error(err);
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (userId: string) => {
    if (!orgId) return;
    try {
      await removeOrgMember(orgId, userId);
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    } catch (err) {
      console.error(err);
    }
  };

  const roleBadgeColor: Record<string, string> = {
    owner: "bg-amber-100 text-amber-700",
    admin: "bg-blue-100 text-blue-700",
    viewer: "bg-gray-100 text-gray-700",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("members")}</h1>
        {canManage && (
          <button
            onClick={() => setShowForm(!showForm)}
            className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
          >
            <UserPlus className="h-4 w-4" />
            {t("addMember")}
          </button>
        )}
      </div>

      {showForm && (
        <div className="rounded-lg border bg-white p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("memberEmail")}
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              className="w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("memberRole")}
            </label>
            <select
              value={memberRole}
              onChange={(e) => setMemberRole(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
            >
              <option value="viewer">{t("viewer")}</option>
              <option value="admin">{t("admin")}</option>
              <option value="owner">{t("owner")}</option>
            </select>
          </div>
          <button
            onClick={handleAdd}
            disabled={adding || !email}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {adding ? "..." : t("addMember")}
          </button>
        </div>
      )}

      <div className="rounded-lg border bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600 hidden md:table-cell">
                Email
              </th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">
                {t("memberRole")}
              </th>
              {canManage && (
                <th className="px-4 py-3 text-right font-medium text-gray-600">Actions</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y">
            {members.map((m) => (
              <tr key={m.user_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{m.name}</td>
                <td className="px-4 py-3 text-gray-600 hidden md:table-cell">
                  {m.email || "-"}
                </td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      roleBadgeColor[m.role] || "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {t(m.role as "owner" | "admin" | "viewer")}
                  </span>
                </td>
                {canManage && (
                  <td className="px-4 py-3 text-right">
                    {m.role !== "owner" && (
                      <button
                        onClick={() => handleRemove(m.user_id)}
                        className="text-red-500 hover:text-red-700"
                        title={t("removeMember")}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
