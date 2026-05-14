"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import type { CourseQualityRunDetail, UnitQualitySummary } from "@/lib/api-quality";
import { FLAGGED_STATUSES } from "@/lib/api-quality";
import { QualityStatusBadge } from "./quality-status-badge";
import { ScorePill } from "./score-pill";

function fmtDate(iso: string | null, locale: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(locale, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function NeedsReviewQueue({
  courseId,
  latestRun,
}: {
  courseId: string;
  latestRun: CourseQualityRunDetail | null;
}) {
  const t = useTranslations("Admin.qualityAgent.needsReview");
  const locale = useLocale();

  const flagged: UnitQualitySummary[] = (latestRun?.units ?? []).filter((u) =>
    FLAGGED_STATUSES.has(u.quality_status),
  );

  if (!latestRun) {
    return (
      <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        {t("noRun")}
      </div>
    );
  }

  if (flagged.length === 0) {
    return (
      <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        {t("allClear")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/30 text-left text-muted-foreground">
            <th className="px-3 py-2">{t("unit")}</th>
            <th className="px-3 py-2">{t("type")}</th>
            <th className="px-3 py-2">{t("language")}</th>
            <th className="px-3 py-2">{t("status")}</th>
            <th className="px-3 py-2">{t("score")}</th>
            <th className="px-3 py-2">{t("flags")}</th>
            <th className="px-3 py-2">{t("attempts")}</th>
            <th className="px-3 py-2">{t("lastAssessed")}</th>
          </tr>
        </thead>
        <tbody>
          {flagged.map((u) => (
            <tr key={u.generated_content_id} className="border-b last:border-0 hover:bg-muted/20">
              <td className="px-3 py-2 font-medium">
                <Link
                  href={`/admin/courses/${courseId}/quality/runs/${latestRun.id}/units/${u.generated_content_id}`}
                  className="text-primary hover:underline"
                >
                  {u.unit_number ?? "—"}
                </Link>
              </td>
              <td className="px-3 py-2 text-muted-foreground">{u.content_type}</td>
              <td className="px-3 py-2 text-muted-foreground uppercase">{u.language}</td>
              <td className="px-3 py-2">
                <QualityStatusBadge status={u.quality_status} />
              </td>
              <td className="px-3 py-2">
                <ScorePill score={u.quality_score} />
              </td>
              <td className="px-3 py-2 tabular-nums">{u.flag_count}</td>
              <td className="px-3 py-2 tabular-nums text-muted-foreground">
                {u.regeneration_attempts}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-xs text-muted-foreground">
                {fmtDate(u.last_assessed_at, locale)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
