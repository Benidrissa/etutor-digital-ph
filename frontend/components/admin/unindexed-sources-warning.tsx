"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Publish-time warning for sources whose extracted text never reached the RAG
 * (#2663). Lessons on their topics would be grounded in the other sources, so
 * the backend refuses to publish until the admin chooses "publish anyway".
 * Shared by both creation wizards and the course list's publish dialog.
 */
export function UnindexedSourcesWarning({ files }: { files: string[] }) {
  const t = useTranslations("AdminCourses.wizard.publishGuard");

  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{t("unindexedWarning", { count: files.length, files: files.join(", ") })}</span>
    </div>
  );
}
