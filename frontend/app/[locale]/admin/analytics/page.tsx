"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { UsageTab } from "@/components/admin/analytics/usage-tab";
import { AiCostsTab } from "@/components/admin/analytics/ai-costs-tab";

const PERIODS = [7, 30, 90] as const;

export default function AnalyticsPage() {
  const t = useTranslations("Admin.analytics");
  const [period, setPeriod] = useState<number>(7);

  const periodLabels: Record<number, string> = {
    7: t("period7d"),
    30: t("period30d"),
    90: t("period90d"),
  };

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </div>
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                period === p
                  ? "bg-background text-foreground shadow-sm font-medium"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {periodLabels[p]}
            </button>
          ))}
        </div>
      </div>

      <Tabs defaultValue="usage">
        <TabsList>
          <TabsTrigger value="usage">{t("tabUsage")}</TabsTrigger>
          <TabsTrigger value="aiCosts">{t("tabAiCosts")}</TabsTrigger>
        </TabsList>
        <TabsContent value="usage" className="mt-4">
          <UsageTab period={period} />
        </TabsContent>
        <TabsContent value="aiCosts" className="mt-4">
          <AiCostsTab period={period} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
