"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, FileText } from "lucide-react";
import {
  getCourseResources,
  type CourseResourceStatus,
} from "@/lib/api-course-admin";
import { SourceStatusBadge } from "@/components/admin/source-status-badge";

/**
 * Per-source "really used in RAG" panel: lists every uploaded source (DB-driven,
 * so failed/deduped/missing-on-disk sources appear too) with its indexed-chunk
 * status, and warns prominently when any source was dropped (failed extraction or
 * 0 chunks). Reused in the creation wizards' indexation recap and the persistent
 * course Sources page.
 *
 * `refreshKey` change → refetch (the wizard passes the live chunk count so the
 * panel updates as indexation lands).
 */
export function CourseSourcesUsage({
  courseId,
  refreshKey,
}: {
  courseId: string;
  refreshKey?: unknown;
}) {
  const t = useTranslations("AdminCourses.wizard.sourcesUsage");
  const [sources, setSources] = useState<CourseResourceStatus[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await getCourseResources(courseId);
      setSources(data.files);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getCourseResources(courseId);
        if (!cancelled) setSources(data.files);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [courseId, refreshKey]);

  if (loading && sources === null) {
    return <p className="text-xs text-muted-foreground">{t("loading")}</p>;
  }
  if (error) {
    return (
      <button
        type="button"
        onClick={load}
        className="text-xs text-destructive underline-offset-2 hover:underline"
      >
        {t("error")}
      </button>
    );
  }
  if (!sources || sources.length === 0) return null;

  const dropped = sources.filter(
    (s) => s.extraction_status === "failed" || s.chunks_indexed === 0
  );

  return (
    <div className="space-y-2">
      {dropped.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{t("droppedWarning", { count: dropped.length })}</span>
        </div>
      )}
      <ul className="divide-y rounded-lg border">
        {sources.map((s) => (
          <li
            key={s.resource_id}
            className="flex items-center gap-2.5 px-3 py-2"
          >
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-xs font-medium">
              {s.name}
            </span>
            <SourceStatusBadge
              status={s.extraction_status}
              chunks={s.chunks_indexed}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
