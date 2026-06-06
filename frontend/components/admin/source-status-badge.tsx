"use client";

import { CheckCircle2, AlertCircle, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ExtractionStatus } from "@/lib/api-course-admin";

/**
 * Per-source "really used in RAG" badge, shared by the wizards' attached-resources
 * lists, the indexation recap, and the course Sources panel.
 *
 * The definitive "used" signal is `chunks_indexed` (DocumentChunk rows tied to the
 * resource). A source can be extraction_status="done" yet contribute 0 chunks
 * (e.g. file_not_found #2424, or not indexed yet) — that must read as NOT used.
 *
 * `chunks` undefined = count not known yet (pre-indexation); 0 = known-and-empty.
 */
export function SourceStatusBadge({
  status,
  chunks,
}: {
  status?: ExtractionStatus;
  chunks?: number;
}) {
  const t = useTranslations("AdminCourses.wizard.sourceStatus");

  if (status === "failed") {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-destructive">
        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
        {t("failed")}
      </span>
    );
  }

  if (status === "pending" || status === "extracting") {
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        <div className="h-3 w-3 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
        {t("extracting")}
      </span>
    );
  }

  // status === "done" (or unknown but uploaded)
  if (typeof chunks === "number" && chunks > 0) {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-green-700 dark:text-green-400">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600" />
        {t("usedChunks", { count: chunks })}
      </span>
    );
  }

  if (chunks === 0) {
    // Extracted but no chunks in RAG — this source is NOT used. Warn clearly.
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        {t("notIndexed")}
      </span>
    );
  }

  // Extracted, chunk count not yet known (indexation not run / in progress).
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
      {t("extracted")}
    </span>
  );
}
