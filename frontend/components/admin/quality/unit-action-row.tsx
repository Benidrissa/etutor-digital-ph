"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { resolveUnit, unlockUnit } from "@/lib/api-quality";

export function UnitActionRow({
  courseId,
  contentId,
  isLocked,
  onResolved,
  onUnlocked,
}: {
  courseId: string;
  contentId: string;
  isLocked: boolean;
  onResolved?: () => void;
  onUnlocked?: () => void;
}) {
  const t = useTranslations("Admin.qualityAgent");
  const queryClient = useQueryClient();

  const [resolveOpen, setResolveOpen] = useState(false);
  const [note, setNote] = useState("");

  const invalidateTree = () => {
    queryClient.invalidateQueries({
      queryKey: ["admin", "quality", courseId],
    });
  };

  const resolveMut = useMutation({
    mutationFn: () =>
      resolveUnit(courseId, contentId, { note: note.trim() || null }),
    onSuccess: () => {
      invalidateTree();
      setResolveOpen(false);
      setNote("");
      onResolved?.();
    },
  });

  const unlockMut = useMutation({
    mutationFn: () => unlockUnit(courseId, contentId),
    onSuccess: () => {
      invalidateTree();
      onUnlocked?.();
    },
  });

  const error = resolveMut.error ?? unlockMut.error;
  const errorMessage =
    error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div className="space-y-3 rounded-md border p-4">
      <h3 className="text-sm font-semibold">{t("unit.actions.title")}</h3>

      <div className="flex flex-wrap items-start gap-2">
        {!resolveOpen ? (
          <Button
            type="button"
            variant="default"
            onClick={() => setResolveOpen(true)}
            disabled={resolveMut.isPending}
          >
            {t("unit.actions.resolve")}
          </Button>
        ) : (
          <div className="flex w-full max-w-xl flex-col gap-2">
            <label htmlFor="resolve-note" className="text-sm font-medium">
              {t("unit.actions.note")}
            </label>
            <textarea
              id="resolve-note"
              className="min-h-20 rounded-md border bg-background p-2 text-sm"
              placeholder={t("unit.actions.notePlaceholder")}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              disabled={resolveMut.isPending}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                onClick={() => resolveMut.mutate()}
                disabled={resolveMut.isPending}
              >
                {resolveMut.isPending ? (
                  <>
                    <Loader2 className="mr-2 size-4 animate-spin" />
                    {t("unit.actions.submitting")}
                  </>
                ) : (
                  t("unit.actions.resolveSubmit")
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setResolveOpen(false);
                  setNote("");
                  resolveMut.reset();
                }}
                disabled={resolveMut.isPending}
              >
                {t("unit.actions.cancel")}
              </Button>
            </div>
          </div>
        )}

        {isLocked && !resolveOpen && (
          <Button
            type="button"
            variant="outline"
            onClick={() => unlockMut.mutate()}
            disabled={unlockMut.isPending}
          >
            {unlockMut.isPending ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                {t("unit.actions.submitting")}
              </>
            ) : (
              t("unit.actions.unlock")
            )}
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        {isLocked ? t("unit.actions.helpLocked") : t("unit.actions.help")}
      </p>

      {errorMessage && (
        <p className="text-sm text-destructive" role="alert">
          {t("unit.actions.error")}: {errorMessage}
        </p>
      )}
    </div>
  );
}
