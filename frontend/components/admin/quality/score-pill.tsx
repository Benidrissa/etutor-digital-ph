"use client";

import { cn } from "@/lib/utils";

function colorFor(score: number) {
  if (score >= 90) return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200";
  if (score >= 70) return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200";
  return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200";
}

export function ScorePill({
  score,
  className,
}: {
  score: number | null | undefined;
  className?: string;
}) {
  if (score === null || score === undefined) {
    return <span className={cn("text-muted-foreground text-xs", className)}>—</span>;
  }
  const rounded = Math.round(score);
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium tabular-nums",
        colorFor(rounded),
        className,
      )}
    >
      {rounded}
    </span>
  );
}
