"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import { fetchOrgSummary, fetchOrgLearners, exportOrgCsv } from "@/lib/api";
import type { OrgSummary, LearnerProgress } from "@/lib/api";
import { Download, Users, QrCode, BarChart3, TrendingUp } from "lucide-react";

export default function OrgReportsPage() {
  const t = useTranslations("Organization");
  const { orgId } = useOrg();
  const [summary, setSummary] = useState<OrgSummary | null>(null);
  const [learners, setLearners] = useState<LearnerProgress[]>([]);

  useEffect(() => {
    if (!orgId) return;
    fetchOrgSummary(orgId).then(setSummary).catch(() => {});
    fetchOrgLearners(orgId, { limit: 50 }).then(setLearners).catch(() => {});
  }, [orgId]);

  const handleExport = async () => {
    if (!orgId) return;
    try {
      const csv = await exportOrgCsv(orgId);
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "org_learners.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
    }
  };

  const stats = summary
    ? [
        { label: t("totalCodes"), value: summary.total_codes, icon: QrCode },
        { label: t("activeCodes"), value: summary.active_codes, icon: QrCode },
        { label: t("totalLearners"), value: summary.unique_learners, icon: Users },
        {
          label: t("avgCompletion"),
          value: `${summary.avg_completion_pct}%`,
          icon: TrendingUp,
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("reports")}</h1>
        <button
          onClick={handleExport}
          className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50"
        >
          <Download className="h-4 w-4" />
          {t("export")}
        </button>
      </div>

      {stats.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {stats.map((stat) => {
            const Icon = stat.icon;
            return (
              <div key={stat.label} className="rounded-lg border bg-white p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon className="h-4 w-4 text-gray-400" />
                  <span className="text-sm text-gray-600">{stat.label}</span>
                </div>
                <p className="text-2xl font-bold">{stat.value}</p>
              </div>
            );
          })}
        </div>
      )}

      <div className="rounded-lg border bg-white overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50">
          <h2 className="font-medium">{t("learnerProgress")}</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600 hidden md:table-cell">
                Email
              </th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">Courses</th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">Completion</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600 hidden md:table-cell">
                Activated
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {learners.map((l) => (
              <tr key={l.user_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{l.name}</td>
                <td className="px-4 py-3 text-gray-600 hidden md:table-cell">
                  {l.email || "-"}
                </td>
                <td className="px-4 py-3 text-center">{l.courses_enrolled}</td>
                <td className="px-4 py-3 text-center">
                  <div className="flex items-center justify-center gap-2">
                    <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-green-500 rounded-full"
                        style={{ width: `${Math.min(l.avg_completion_pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600">
                      {l.avg_completion_pct}%
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-right text-gray-500 text-xs hidden md:table-cell">
                  {l.activated_at
                    ? new Date(l.activated_at).toLocaleDateString()
                    : "-"}
                </td>
              </tr>
            ))}
            {learners.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  No learners enrolled yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
