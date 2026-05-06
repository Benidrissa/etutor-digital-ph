"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  type CourseQualityRunDetail,
  type QualityStatus,
  FLAGGED_STATUSES,
  getQualityRun,
  isRunInProgress,
} from "@/lib/api-quality";
import { QualityStatusBadge, RunStatusBadge } from "./quality-status-badge";
import { ScorePill } from "./score-pill";

const POLL_MS = 10_000;

type Filter = "all" | "flagged" | QualityStatus;

const FILTER_ORDER: Filter[] = [
  "all",
  "flagged",
  "passing",
  "needs_review",
  "needs_review_final",
  "failed",
  "manual_override",
];

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

function durationLabel(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return `${h}h ${min % 60}m`;
}

export function RunDetailClient({
  courseId,
  runId,
}: {
  courseId: string;
  runId: string;
}) {
  const t = useTranslations("Admin.qualityAgent.runDetail");
  const tStatus = useTranslations("Admin.qualityAgent.unitStatus");
  const tKind = useTranslations("Admin.qualityAgent.runKind");
  const locale = useLocale();
  const [filter, setFilter] = useState<Filter>("all");

  const runQ = useQuery<CourseQualityRunDetail>({
    queryKey: ["admin", "quality", courseId, "run", runId],
    queryFn: () => getQualityRun(courseId, runId),
    refetchInterval: (q) =>
      isRunInProgress(q.state.data?.status) ? POLL_MS : false,
  });

  const filteredUnits = useMemo(() => {
    const units = runQ.data?.units ?? [];
    if (filter === "all") return units;
    if (filter === "flagged") {
      return units.filter((u) => FLAGGED_STATUSES.has(u.quality_status));
    }
    return units.filter((u) => u.quality_status === filter);
  }, [runQ.data, filter]);

  if (runQ.isLoading) {
    return <p className="py-12 text-center text-sm text-muted-foreground">{t("loading")}</p>;
  }

  if (runQ.error) {
    const msg = runQ.error instanceof Error ? runQ.error.message : t("error");
    return (
      <p className="py-12 text-center text-sm text-destructive" role="alert">
        {msg}
      </p>
    );
  }

  const run = runQ.data;
  if (!run) {
    return <p className="py-12 text-center text-sm text-muted-foreground">{t("notFound")}</p>;
  }

  const duration = durationLabel(run.started_at, run.finished_at);

  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-col gap-2">
        <Link
          href={`/admin/courses/${courseId}/quality`}
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("backToCourseQuality")}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold">{t("headerLine", { kind: tKind(run.run_kind) })}</h2>
          <RunStatusBadge status={run.status} />
          <ScorePill score={run.overall_score} />
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
          <div>
            <dt className="font-medium">{t("started")}</dt>
            <dd>{fmtDate(run.started_at ?? run.created_at, locale)}</dd>
          </div>
          <div>
            <dt className="font-medium">{t("finished")}</dt>
            <dd>{fmtDate(run.finished_at, locale)}</dd>
          </div>
          {duration && (
            <div>
              <dt className="font-medium">{t("duration")}</dt>
              <dd>{duration}</dd>
            </div>
          )}
          <div>
            <dt className="font-medium">{t("credits")}</dt>
            <dd className="tabular-nums">
              {run.spent_credits} / {run.budget_credits}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{t("unitsCounter")}</dt>
            <dd className="tabular-nums">
              {run.units_passing} / {run.units_total}
            </dd>
          </div>
          {run.units_regenerated > 0 && (
            <div>
              <dt className="font-medium">{t("regenerated")}</dt>
              <dd className="tabular-nums">{run.units_regenerated}</dd>
            </div>
          )}
        </dl>
        {run.notes && (
          <p className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            {run.notes}
          </p>
        )}
      </div>

      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-lg font-semibold">
            {t("unitsTitle", { count: run.units.length })}
          </h3>
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="run-filter" className="text-muted-foreground">
              {t("filterLabel")}
            </label>
            <select
              id="run-filter"
              className="rounded-md border bg-background px-2 py-1 text-sm"
              value={filter}
              onChange={(e) => setFilter(e.target.value as Filter)}
            >
              {FILTER_ORDER.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === "all"
                    ? t("filterAll")
                    : opt === "flagged"
                      ? t("filterFlagged")
                      : tStatus(opt as QualityStatus)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {filteredUnits.length === 0 ? (
          <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
            {filter === "all" ? t("emptyAll") : t("emptyFiltered")}
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30 text-left text-muted-foreground">
                  <th className="px-3 py-2">{t("col.unit")}</th>
                  <th className="px-3 py-2">{t("col.type")}</th>
                  <th className="px-3 py-2">{t("col.language")}</th>
                  <th className="px-3 py-2">{t("col.status")}</th>
                  <th className="px-3 py-2">{t("col.score")}</th>
                  <th className="px-3 py-2">{t("col.flags")}</th>
                  <th className="px-3 py-2">{t("col.attempts")}</th>
                  <th className="px-3 py-2">{t("col.lastAssessed")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredUnits.map((u) => (
                  <tr
                    key={u.generated_content_id}
                    className="border-b last:border-0 hover:bg-muted/20"
                  >
                    <td className="px-3 py-2 font-medium">
                      <Link
                        href={`/admin/courses/${courseId}/quality/runs/${runId}/units/${u.generated_content_id}`}
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
        )}
      </section>
    </div>
  );
}
