"use client";

import { useLocale, useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import type { QualitySummary } from "@/lib/api-quality";
import { FLAGGED_STATUSES } from "@/lib/api-quality";
import { RunStatusBadge } from "./quality-status-badge";
import { ScorePill } from "./score-pill";

function relativeTime(isoOrNull: string | null | undefined, locale: string) {
  if (!isoOrNull) return null;
  const then = new Date(isoOrNull).getTime();
  const now = Date.now();
  const diffSec = Math.round((then - now) / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  return rtf.format(Math.round(diffSec / 86400), "day");
}

function flaggedCount(summary: QualitySummary): number {
  let count = 0;
  for (const s of FLAGGED_STATUSES) {
    count += summary.units_by_status[s] ?? 0;
  }
  return count;
}

export function QualitySummaryTiles({ summary }: { summary: QualitySummary }) {
  const t = useTranslations("Admin.qualityAgent.tiles");
  const locale = useLocale();
  const flagged = flaggedCount(summary);
  const lastRun = summary.last_run;
  const lastRunRel = relativeTime(lastRun?.finished_at ?? lastRun?.started_at, locale);

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card className="p-4">
        <div className="text-sm text-muted-foreground">{t("unitsTotal")}</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{summary.units_total}</div>
      </Card>

      <Card className="p-4">
        <div className="text-sm text-muted-foreground">{t("needsReview")}</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums">{flagged}</span>
          {flagged > 0 && (
            <span className="text-xs text-amber-700 dark:text-amber-300">{t("needsReviewHint")}</span>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <div className="text-sm text-muted-foreground">{t("glossaryDrift")}</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums">{summary.glossary_drift_count}</span>
          {summary.glossary_drift_count > 0 && (
            <span className="text-xs text-amber-700 dark:text-amber-300">{t("driftHint")}</span>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <div className="text-sm text-muted-foreground">{t("lastRun")}</div>
        {lastRun ? (
          <div className="mt-1 flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <RunStatusBadge status={lastRun.status} />
              <ScorePill score={lastRun.overall_score} />
            </div>
            {lastRunRel && (
              <div className="text-xs text-muted-foreground">{lastRunRel}</div>
            )}
          </div>
        ) : (
          <div className="mt-1 text-sm text-muted-foreground">{t("noRun")}</div>
        )}
      </Card>
    </div>
  );
}
