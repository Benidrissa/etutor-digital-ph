"use client";

import Link from "next/link";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type ReviewQueueEntry, getReviewQueue } from "@/lib/api-quality";
import { RunStatusBadge } from "./quality-status-badge";

function fmtRel(iso: string | null, locale: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.round((then - now) / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  return rtf.format(Math.round(diffSec / 86400), "day");
}

function attentionScore(e: ReviewQueueEntry): number {
  return e.units_needs_review_final + e.units_failed;
}

export function ReviewQueueClient() {
  const t = useTranslations("Admin.qualityAgent.reviewQueue");
  const locale = useLocale();
  const [hasIssues, setHasIssues] = useState(true);

  const queueQ = useQuery<ReviewQueueEntry[]>({
    queryKey: ["admin", "quality", "review-queue", hasIssues],
    queryFn: () => getReviewQueue({ hasIssues, limit: 200 }),
  });

  const entries = queueQ.data ?? [];

  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{t("intro")}</p>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={hasIssues}
            onChange={(e) => setHasIssues(e.target.checked)}
            className="size-4"
          />
          {t("filterHasIssues")}
        </label>
      </div>

      {queueQ.isLoading && (
        <p className="py-12 text-center text-sm text-muted-foreground">{t("loading")}</p>
      )}

      {queueQ.error && (
        <p className="py-12 text-center text-sm text-destructive" role="alert">
          {queueQ.error instanceof Error ? queueQ.error.message : t("error")}
        </p>
      )}

      {!queueQ.isLoading && !queueQ.error && entries.length === 0 && (
        <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
          {hasIssues ? t("emptyClean") : t("emptyAll")}
        </div>
      )}

      {!queueQ.isLoading && !queueQ.error && entries.length > 0 && (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-left text-muted-foreground">
                <th className="px-3 py-2">{t("col.course")}</th>
                <th className="px-3 py-2">{t("col.attention")}</th>
                <th className="px-3 py-2">{t("col.passing")}</th>
                <th className="px-3 py-2">{t("col.drift")}</th>
                <th className="px-3 py-2">{t("col.lastAssessed")}</th>
                <th className="px-3 py-2">{t("col.lastRun")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const attn = attentionScore(e);
                const title = locale === "fr" ? e.course_title_fr : e.course_title_en;
                return (
                  <tr
                    key={e.course_id}
                    className={cn(
                      "border-b last:border-0 align-top",
                      attn > 0
                        ? "bg-amber-50/40 hover:bg-amber-100/40 dark:bg-amber-950/20"
                        : "hover:bg-muted/20",
                    )}
                  >
                    <td className="px-3 py-2 font-medium max-w-md">
                      <Link
                        href={`/admin/courses/${e.course_id}/quality`}
                        className="text-primary hover:underline"
                      >
                        {title}
                      </Link>
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {attn > 0 ? (
                        <span className="inline-flex items-center gap-1 font-semibold text-red-700 dark:text-red-300">
                          <AlertTriangle className="size-3" aria-hidden="true" />
                          {attn}
                        </span>
                      ) : e.units_needs_review > 0 ? (
                        <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300">
                          {e.units_needs_review}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                      {(e.units_needs_review_final > 0 || e.units_failed > 0) && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          ({e.units_needs_review_final} · {e.units_failed})
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">
                      {e.units_passing}/{e.units_total}
                    </td>
                    <td className="px-3 py-2">
                      {e.glossary_drift_count > 0 ? (
                        <Badge variant="destructive">{e.glossary_drift_count}</Badge>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs text-muted-foreground">
                      {fmtRel(e.last_assessed_at, locale)}
                    </td>
                    <td className="px-3 py-2">
                      {e.last_run ? <RunStatusBadge status={e.last_run.status} /> : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
