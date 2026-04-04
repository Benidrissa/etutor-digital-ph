"use client";

import { useEffect, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { CostBreakdown } from "@/components/expert/cost-breakdown";

const OPERATION_KEYS = [
  "lesson_generation",
  "quiz_generation",
  "case_study_generation",
  "flashcard_generation",
  "tutor_chat",
] as const;

interface CourseGenerationCost {
  courseId: string;
  courseTitle: string;
  totalCostUsd: number;
  apiCalls: number;
  lastUsedAt: string | null;
}

interface UsageLogEntry {
  id: string;
  createdAt: string;
  courseTitle: string;
  operation: string;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
}

interface CreditsData {
  balance: number;
  courses: CourseGenerationCost[];
  usageLogs: UsageLogEntry[];
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function CreditsClient() {
  const t = useTranslations("ExpertCredits");
  const locale = useLocale();
  const [data, setData] = useState<CreditsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const token = getStoredToken();
        const res = await fetch("/api/v1/expert/credits", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error("fetch failed");
        const json = (await res.json()) as CreditsData;
        setData(json);
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

  if (error || !data) {
    return <p className="py-8 text-center text-sm text-destructive">{t("error")}</p>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border bg-card p-4">
        <p className="text-sm text-muted-foreground">{t("balance.title")}</p>
        <p className="mt-1 text-3xl font-bold tabular-nums">
          {t("balance.credits", { count: data.balance })}
        </p>
        <div className="mt-3">
          <Link
            href={`/${locale}/billing/purchase`}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            {t("balance.purchase")}
          </Link>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-4 text-sm font-semibold">{t("breakdown.title")}</h2>
        <CostBreakdown courses={data.courses} />
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-4 text-sm font-semibold">{t("history.title")}</h2>
        {data.usageLogs.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">{t("history.noHistory")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">{t("history.date")}</th>
                  <th className="py-2 pr-4 font-medium">{t("history.course")}</th>
                  <th className="py-2 pr-4 font-medium">{t("history.operation")}</th>
                  <th className="py-2 pr-4 font-medium text-right">{t("history.tokensIn")}</th>
                  <th className="py-2 pr-4 font-medium text-right">{t("history.tokensOut")}</th>
                  <th className="py-2 font-medium text-right">{t("history.cost")}</th>
                </tr>
              </thead>
              <tbody>
                {data.usageLogs.map((log) => (
                  <tr key={log.id} className="border-b last:border-0">
                    <td className="py-2.5 pr-4 text-muted-foreground">
                      {new Date(log.createdAt).toLocaleDateString()}
                    </td>
                    <td className="py-2.5 pr-4 max-w-[10rem] truncate">{log.courseTitle}</td>
                    <td className="py-2.5 pr-4 text-muted-foreground">
                      {(OPERATION_KEYS as ReadonlyArray<string>).includes(log.operation)
                        ? t(`operations.${log.operation as typeof OPERATION_KEYS[number]}`)
                        : log.operation}
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">{log.tokensIn.toLocaleString()}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">{log.tokensOut.toLocaleString()}</td>
                    <td className="py-2.5 text-right tabular-nums">${log.costUsd.toFixed(4)}</td>
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
