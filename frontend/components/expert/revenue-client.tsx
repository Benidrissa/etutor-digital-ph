"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { RevenueChart } from "@/components/expert/revenue-chart";

interface MonthlyRevenue {
  month: string;
  gross: number;
  commission: number;
  net: number;
}

interface Transaction {
  id: string;
  date: string;
  description: string;
  gross: number;
  commission: number;
  net: number;
}

interface RevenueSummary {
  totalEarned: number;
  totalCommission: number;
  netEarnings: number;
  monthly: MonthlyRevenue[];
  transactions: Transaction[];
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function RevenueClient() {
  const t = useTranslations("ExpertRevenue");
  const [summary, setSummary] = useState<RevenueSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const token = getStoredToken();
        const res = await fetch("/api/v1/expert/revenue", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error("fetch failed");
        const data = (await res.json()) as RevenueSummary;
        setSummary(data);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <p className="py-8 text-center text-sm text-muted-foreground">{t("loading")}</p>;
  }

  if (error || !summary) {
    return <p className="py-8 text-center text-sm text-destructive">{t("error")}</p>;
  }

  const summaryItems = [
    { label: t("summaryCards.totalEarned"), value: summary.totalEarned },
    { label: t("summaryCards.totalCommission"), value: summary.totalCommission },
    { label: t("summaryCards.netEarnings"), value: summary.netEarnings },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {summaryItems.map((item) => (
          <div key={item.label} className="rounded-lg border bg-card p-4">
            <p className="text-sm text-muted-foreground">{item.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              ${item.value.toFixed(2)}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-4 text-sm font-semibold">{t("chart.title")}</h2>
        <RevenueChart data={summary.monthly} />
      </div>

      <div className="rounded-lg border bg-card p-4">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{t("transactions.title")}</h2>
          <button
            disabled
            className="rounded border px-3 py-1.5 text-xs text-muted-foreground opacity-50"
          >
            {t("export")}
          </button>
        </div>
        {summary.transactions.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">
            {t("transactions.noTransactions")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">{t("transactions.date")}</th>
                  <th className="py-2 pr-4 font-medium">{t("transactions.description")}</th>
                  <th className="py-2 pr-4 font-medium text-right">{t("transactions.gross")}</th>
                  <th className="py-2 pr-4 font-medium text-right">{t("transactions.commission")}</th>
                  <th className="py-2 font-medium text-right">{t("transactions.net")}</th>
                </tr>
              </thead>
              <tbody>
                {summary.transactions.map((tx) => (
                  <tr key={tx.id} className="border-b last:border-0">
                    <td className="py-2.5 pr-4 text-muted-foreground">
                      {new Date(tx.date).toLocaleDateString()}
                    </td>
                    <td className="py-2.5 pr-4">{tx.description}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">
                      ${tx.gross.toFixed(2)}
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-amber-600">
                      -${tx.commission.toFixed(2)}
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-emerald-600">
                      ${tx.net.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
