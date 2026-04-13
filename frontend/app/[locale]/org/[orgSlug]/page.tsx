"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import { fetchOrgSummary, fetchOrgCredits } from "@/lib/api";
import type { OrgSummary } from "@/lib/api";
import { QrCode, Users, BarChart3, Wallet } from "lucide-react";

export default function OrgDashboardPage() {
  const t = useTranslations("Organization");
  const { org, orgId } = useOrg();
  const [summary, setSummary] = useState<OrgSummary | null>(null);
  const [balance, setBalance] = useState<number>(0);

  useEffect(() => {
    if (!orgId) return;
    fetchOrgSummary(orgId).then(setSummary).catch(() => {});
    fetchOrgCredits(orgId).then((d) => setBalance(d.balance)).catch(() => {});
  }, [orgId]);

  if (!org) return null;

  const stats = [
    {
      label: t("totalCodes"),
      value: summary?.total_codes ?? 0,
      icon: QrCode,
      color: "text-blue-600 bg-blue-50",
    },
    {
      label: t("totalLearners"),
      value: summary?.unique_learners ?? 0,
      icon: Users,
      color: "text-green-600 bg-green-50",
    },
    {
      label: t("avgCompletion"),
      value: `${summary?.avg_completion_pct ?? 0}%`,
      icon: BarChart3,
      color: "text-purple-600 bg-purple-50",
    },
    {
      label: t("credits"),
      value: balance,
      icon: Wallet,
      color: "text-amber-600 bg-amber-50",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{org.name}</h1>
        {org.description && (
          <p className="text-gray-600 mt-1">{org.description}</p>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="rounded-lg border bg-white p-4 shadow-sm"
            >
              <div className="flex items-center gap-3">
                <div className={`rounded-lg p-2 ${stat.color}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm text-gray-600">{stat.label}</p>
                  <p className="text-xl font-bold">{stat.value}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
