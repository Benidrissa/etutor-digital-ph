"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getSyncManager, type SyncStatus } from "@/lib/offline/sync-manager";

export function SyncStatusIndicator() {
  const t = useTranslations("Sync");
  const [status, setStatus] = useState<SyncStatus>({
    state: "idle",
    pendingCount: 0,
    lastSyncedCounts: null,
  });
  const [showSuccess, setShowSuccess] = useState(false);

  useEffect(() => {
    const manager = getSyncManager();
    const unsubscribe = manager.subscribe((s) => {
      setStatus((prev) => {
        if (
          prev.lastSyncedCounts === null &&
          s.lastSyncedCounts !== null
        ) {
          setShowSuccess(true);
          setTimeout(() => setShowSuccess(false), 5000);
        }
        return s;
      });
    });
    return unsubscribe;
  }, []);

  if (showSuccess && status.lastSyncedCounts) {
    const counts = status.lastSyncedCounts;
    const parts: string[] = [];
    if (counts.quiz_attempt > 0) {
      parts.push(
        t("successQuiz", { count: counts.quiz_attempt })
      );
    }
    if (counts.flashcard_review > 0) {
      parts.push(
        t("successFlashcards", { count: counts.flashcard_review })
      );
    }
    if (counts.lesson_reading > 0) {
      parts.push(
        t("successLessons", { count: counts.lesson_reading })
      );
    }
    const message = parts.join(", ");

    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
        {message}
      </div>
    );
  }

  if (status.state === "syncing") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
      >
        <span
          className="h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"
          aria-hidden="true"
        />
        {t("syncing")}
      </div>
    );
  }

  if (status.pendingCount > 0) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
        {t("pending", { count: status.pendingCount })}
      </div>
    );
  }

  return null;
}
