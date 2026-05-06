"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  type CourseQualityRunDetail,
  type CourseQualityRunSummary,
  type QualitySummary,
  getQualityRun,
  getQualitySummary,
  isRunInProgress,
  listQualityRuns,
} from "@/lib/api-quality";
import { NeedsReviewQueue } from "./needs-review-queue";
import { QualitySummaryTiles } from "./quality-summary-tiles";
import { RunsLog } from "./runs-log";

const POLL_MS = 10_000;

export function QualityClient({ courseId }: { courseId: string }) {
  const t = useTranslations("Admin.qualityAgent");

  const summaryQ = useQuery<QualitySummary>({
    queryKey: ["admin", "quality", courseId, "summary"],
    queryFn: () => getQualitySummary(courseId),
    refetchInterval: (q) =>
      isRunInProgress(q.state.data?.last_run?.status) ? POLL_MS : false,
  });

  const runsQ = useQuery<CourseQualityRunSummary[]>({
    queryKey: ["admin", "quality", courseId, "runs"],
    queryFn: () => listQualityRuns(courseId, 10),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => isRunInProgress(r.status)) ? POLL_MS : false,
  });

  // Latest *completed* run drives the needs-review queue. If the only runs
  // are in-progress, fall back to the most recent overall — its `units` will
  // be empty until the worker scores them, but the empty-state message is
  // truthful then.
  const latestCompleted =
    runsQ.data?.find((r) => r.status === "completed") ?? runsQ.data?.[0] ?? null;

  const runDetailQ = useQuery<CourseQualityRunDetail>({
    queryKey: ["admin", "quality", courseId, "run", latestCompleted?.id ?? "none"],
    queryFn: () => getQualityRun(courseId, latestCompleted!.id),
    enabled: !!latestCompleted,
    refetchInterval: () =>
      latestCompleted && isRunInProgress(latestCompleted.status) ? POLL_MS : false,
  });

  if (summaryQ.isLoading || runsQ.isLoading) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">{t("loading")}</p>
    );
  }

  if (summaryQ.error) {
    return (
      <p className="py-12 text-center text-sm text-destructive" role="alert">
        {summaryQ.error instanceof Error ? summaryQ.error.message : t("error")}
      </p>
    );
  }

  const summary = summaryQ.data;
  if (!summary) {
    return <p className="py-12 text-center text-sm text-muted-foreground">{t("noData")}</p>;
  }

  const inProgress = (runsQ.data ?? []).find((r) => isRunInProgress(r.status));

  return (
    <div className="flex flex-col gap-6 p-4">
      {inProgress && (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
          role="status"
        >
          <span className="font-medium">{t("runInProgress.title")}</span>{" "}
          <span>{t("runInProgress.body")}</span>
        </div>
      )}

      <QualitySummaryTiles summary={summary} />

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("sections.needsReview")}</h2>
        <NeedsReviewQueue courseId={courseId} latestRun={runDetailQ.data ?? null} />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("sections.glossary")}</h2>
        <div className="rounded-md border bg-muted/20 p-4 text-sm">
          {summary.glossary_drift_count > 0 ? (
            <p className="mb-2 text-amber-900 dark:text-amber-300">
              {t("glossaryDriftBody", { count: summary.glossary_drift_count })}
            </p>
          ) : (
            <p className="mb-2 text-muted-foreground">{t("glossaryNoDrift")}</p>
          )}
          <Link
            href={`/admin/courses/${courseId}/quality/glossary`}
            className="text-sm text-primary hover:underline"
          >
            {t("viewGlossary")} →
          </Link>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("sections.runsLog")}</h2>
        <RunsLog courseId={courseId} runs={runsQ.data ?? []} />
      </section>
    </div>
  );
}
