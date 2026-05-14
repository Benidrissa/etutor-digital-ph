"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import type { CourseQualityRunSummary } from "@/lib/api-quality";
import { RunStatusBadge } from "./quality-status-badge";
import { ScorePill } from "./score-pill";

function fmtDate(iso: string | null, locale: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RunsLog({
  courseId,
  runs,
}: {
  courseId: string;
  runs: CourseQualityRunSummary[];
}) {
  const t = useTranslations("Admin.qualityAgent.runsLog");
  const tKind = useTranslations("Admin.qualityAgent.runKind");
  const locale = useLocale();

  if (runs.length === 0) {
    return (
      <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        {t("empty")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/30 text-left text-muted-foreground">
            <th className="px-3 py-2">{t("status")}</th>
            <th className="px-3 py-2">{t("kind")}</th>
            <th className="px-3 py-2">{t("started")}</th>
            <th className="px-3 py-2">{t("score")}</th>
            <th className="px-3 py-2">{t("units")}</th>
            <th className="px-3 py-2">{t("credits")}</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-b last:border-0 hover:bg-muted/20">
              <td className="px-3 py-2">
                <RunStatusBadge status={r.status} />
              </td>
              <td className="px-3 py-2 text-muted-foreground">{tKind(r.run_kind)}</td>
              <td className="px-3 py-2 whitespace-nowrap text-xs text-muted-foreground">
                {fmtDate(r.started_at ?? r.created_at, locale)}
              </td>
              <td className="px-3 py-2">
                <ScorePill score={r.overall_score} />
              </td>
              <td className="px-3 py-2 tabular-nums text-muted-foreground">
                {r.units_passing}/{r.units_total}
              </td>
              <td className="px-3 py-2 tabular-nums text-muted-foreground">
                {r.spent_credits}/{r.budget_credits}
              </td>
              <td className="px-3 py-2 text-right">
                <Link
                  href={`/admin/courses/${courseId}/quality/runs/${r.id}`}
                  className="text-xs text-primary hover:underline"
                >
                  {t("open")}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
