"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import {
  DIMENSION_KEYS,
  DIMENSION_WEIGHTS,
  type DimensionKey,
  type DimensionScores,
} from "@/lib/api-quality";

function fillFor(score: number) {
  if (score >= 90) return "bg-green-500 dark:bg-green-500/80";
  if (score >= 70) return "bg-amber-500 dark:bg-amber-500/80";
  return "bg-red-500 dark:bg-red-500/80";
}

export function DimensionBars({
  scores,
}: {
  scores: DimensionScores | null;
}) {
  const t = useTranslations("Admin.qualityAgent");
  const tDim = useTranslations("Admin.qualityAgent.dimensions");

  if (!scores) {
    return (
      <div
        className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground"
        role="note"
      >
        {t("unit.notAssessed")}
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {DIMENSION_KEYS.map((key: DimensionKey) => {
        const score = scores[key];
        const weight = DIMENSION_WEIGHTS[key];
        const clamped = Math.max(0, Math.min(100, score));
        return (
          <li key={key} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium">{tDim(key)}</span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {t("unit.weight", { weight })} · {Math.round(score)}
              </span>
            </div>
            <div
              className="h-2 w-full overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={clamped}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={tDim(key)}
            >
              <div
                className={cn("h-full rounded-full transition-all", fillFor(clamped))}
                style={{ width: `${clamped}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
