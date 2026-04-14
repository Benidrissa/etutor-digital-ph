"use client";

import { useTranslations } from "next-intl";
import { Sparkles, FileText } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
} from "@/components/ui/alert-dialog";

interface CreationModePickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (mode: "legacy" | "ai_assisted") => void;
}

export function CreationModePicker({ open, onClose, onSelect }: CreationModePickerProps) {
  const t = useTranslations("AdminCourses.modePicker");

  return (
    <AlertDialog open={open} onOpenChange={(v) => !v && onClose()}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogTitle>{t("title")}</AlertDialogTitle>
        <AlertDialogDescription>{t("description")}</AlertDialogDescription>

        <div className="mt-4 grid gap-3">
          <button
            type="button"
            onClick={() => onSelect("ai_assisted")}
            className="flex items-start gap-4 rounded-lg border-2 border-transparent bg-card p-4 text-left transition-colors hover:border-primary hover:bg-primary/5 min-h-[72px]"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-sm">{t("aiAssisted")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("aiAssistedDesc")}</p>
            </div>
          </button>

          <button
            type="button"
            onClick={() => onSelect("legacy")}
            className="flex items-start gap-4 rounded-lg border-2 border-transparent bg-card p-4 text-left transition-colors hover:border-primary hover:bg-primary/5 min-h-[72px]"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <FileText className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-sm">{t("legacy")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("legacyDesc")}</p>
            </div>
          </button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
