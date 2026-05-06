"use client";

import Link from "next/link";
import { ArrowLeft, Lock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  type UnitQualityDetail,
  getUnitQualityDetail,
} from "@/lib/api-quality";
import { DimensionBars } from "./dimension-bars";
import { FlagList } from "./flag-list";
import { QualityStatusBadge } from "./quality-status-badge";
import { ScorePill } from "./score-pill";
import { UnitActionRow } from "./unit-action-row";

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

export function UnitQualityClient({
  courseId,
  runId,
  contentId,
}: {
  courseId: string;
  runId: string | null;
  contentId: string;
}) {
  const t = useTranslations("Admin.qualityAgent");
  const locale = useLocale();

  const detailQ = useQuery<UnitQualityDetail>({
    queryKey: ["admin", "quality", courseId, "unit", contentId],
    queryFn: () => getUnitQualityDetail(courseId, contentId),
  });

  if (detailQ.isLoading) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  }

  if (detailQ.error) {
    const msg =
      detailQ.error instanceof Error ? detailQ.error.message : t("error");
    return (
      <p className="py-12 text-center text-sm text-destructive" role="alert">
        {msg}
      </p>
    );
  }

  const detail = detailQ.data;
  if (!detail) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        {t("noData")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-col gap-2">
        <Link
          href={
            runId
              ? `/admin/courses/${courseId}/quality/runs/${runId}`
              : `/admin/courses/${courseId}/quality`
          }
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {runId ? t("unit.backToRun") : t("unit.backToCourseQuality")}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold">
            {t("unit.headerLine", {
              unit_number: detail.unit_number ?? "—",
              type: detail.content_type,
              language: detail.language.toUpperCase(),
            })}
          </h2>
          <QualityStatusBadge status={detail.quality_status} />
          <ScorePill score={detail.quality_score} />
          {detail.regeneration_attempts > 0 && (
            <span className="text-xs text-muted-foreground">
              {t("unit.attempts", { count: detail.regeneration_attempts })}
            </span>
          )}
          {detail.is_manually_edited && (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
              <Lock className="size-3" aria-hidden="true" />
              {t("unit.lockedShort")}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {t("unit.lastAssessed")}: {fmtDate(detail.quality_assessed_at, locale)}
        </p>
        {detail.is_manually_edited && (
          <p className="text-sm text-amber-700 dark:text-amber-300" role="note">
            {t("unit.locked")}
          </p>
        )}
      </div>

      <section>
        <h3 className="mb-3 text-lg font-semibold">{t("unit.sections.dimensions")}</h3>
        <DimensionBars scores={detail.dimension_scores} />
      </section>

      <section>
        <h3 className="mb-3 text-lg font-semibold">
          {t("unit.sections.flags", { count: detail.flag_count })}
        </h3>
        <FlagList flags={detail.quality_flags} />
      </section>

      <section>
        <UnitActionRow
          courseId={courseId}
          contentId={contentId}
          isLocked={detail.is_manually_edited}
        />
      </section>
    </div>
  );
}
