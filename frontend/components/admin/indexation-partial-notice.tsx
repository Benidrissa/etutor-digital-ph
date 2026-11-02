"use client";

import { AlertCircle, Database, RotateCcw } from "lucide-react";
import type { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

interface PartialTask {
  partial?: boolean;
  text_incomplete?: string[];
  images_incomplete?: string[];
}

// Indexation that stops at its time budget still succeeds (#2659), so the
// wizard would otherwise show plain success while some sources have no text
// chunks or incomplete figures. Name them and offer the matching re-run.
export function IndexationPartialNotice({
  task,
  disabled,
  onRetryIndexation,
  onReindexImages,
  t,
}: {
  task?: PartialTask;
  disabled?: boolean;
  onRetryIndexation: () => void;
  onReindexImages: () => void;
  t: ReturnType<typeof useTranslations>;
}) {
  if (!task?.partial) return null;
  const textMissing = task.text_incomplete ?? [];
  const imagesMissing = task.images_incomplete ?? [];

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-amber-500/40 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
        <div className="flex items-start gap-2 text-amber-900 dark:text-amber-200">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-medium">{t("index.partialTitle")}</p>
            {textMissing.length > 0 && (
              <p className="text-xs opacity-90 break-words">
                {t("index.partialText", { files: textMissing.join(", ") })}
              </p>
            )}
            {imagesMissing.length > 0 && (
              <p className="text-xs opacity-90 break-words">
                {t("index.partialImages", { files: imagesMissing.join(", ") })}
              </p>
            )}
          </div>
        </div>
      </div>
      {/* Missing text needs the full pipeline; missing figures only need images. */}
      {textMissing.length > 0 ? (
        <Button
          onClick={onRetryIndexation}
          disabled={disabled}
          variant="outline"
          size="sm"
          className="w-full min-h-[44px]"
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          {t("index.retryIndexation")}
        </Button>
      ) : (
        imagesMissing.length > 0 && (
          <Button
            onClick={onReindexImages}
            disabled={disabled}
            variant="outline"
            size="sm"
            className="w-full min-h-[44px]"
          >
            <Database className="mr-2 h-4 w-4" />
            {t("index.reindexImages")}
          </Button>
        )
      )}
    </div>
  );
}
