"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Plus,
  Trash2,
  Loader2,
  ClipboardList,
  BookOpen,
  RotateCcw,
  X,
} from "lucide-react";
import {
  fetchQBankTestConfigs,
  createQBankTestConfig,
  deleteQBankTestConfig,
} from "@/lib/api";
import type { QBankTestConfig } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface QBankTestConfigProps {
  orgId: string;
  bankId: string;
}

const MODE_ICONS = {
  exam: ClipboardList,
  training: BookOpen,
  review: RotateCcw,
};

const MODE_COLORS = {
  exam: "text-red-600 bg-red-50",
  training: "text-teal-600 bg-teal-50",
  review: "text-amber-600 bg-amber-50",
};

export function QBankTestConfigSection({ orgId, bankId }: QBankTestConfigProps) {
  const t = useTranslations("QBank");
  const [configs, setConfigs] = useState<QBankTestConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [mode, setMode] = useState<"exam" | "training" | "review">("exam");
  const [questionCount, setQuestionCount] = useState<string>("");
  const [timerOverride, setTimerOverride] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [showFeedback, setShowFeedback] = useState(false);

  const load = () => {
    fetchQBankTestConfigs(orgId, bankId)
      .then(setConfigs)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [orgId, bankId]);

  const resetForm = () => {
    setMode("exam");
    setQuestionCount("");
    setTimerOverride("");
    setCategoryFilter("");
    setShowFeedback(false);
    setFormError(null);
  };

  const handleCreate = async () => {
    setFormError(null);
    setSaving(true);
    try {
      const created = await createQBankTestConfig(orgId, bankId, {
        mode,
        question_count: questionCount ? parseInt(questionCount, 10) : null,
        time_per_question_override: timerOverride
          ? parseInt(timerOverride, 10)
          : null,
        category_filter: categoryFilter || null,
        show_feedback: showFeedback,
      });
      setConfigs((prev) => [created, ...prev]);
      setDialogOpen(false);
      resetForm();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deletingId) return;
    setDeleting(true);
    try {
      await deleteQBankTestConfig(orgId, bankId, deletingId);
      setConfigs((prev) => prev.filter((c) => c.id !== deletingId));
    } catch {
    } finally {
      setDeleting(false);
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-stone-800">
          {t("testConfigurations")}
        </h3>
        <Button
          size="sm"
          onClick={() => { resetForm(); setDialogOpen(true); }}
          className="min-h-11 bg-teal-600 hover:bg-teal-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          {t("newTestConfig")}
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-teal-600" />
        </div>
      ) : configs.length === 0 ? (
        <div className="rounded-lg border bg-white p-8 text-center">
          <ClipboardList className="h-10 w-10 text-stone-300 mx-auto mb-3" />
          <p className="text-stone-500">{t("noTestConfigs")}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {configs.map((cfg) => {
            const Icon = MODE_ICONS[cfg.mode] ?? ClipboardList;
            const colorClass = MODE_COLORS[cfg.mode] ?? "text-stone-600 bg-stone-50";
            return (
              <div
                key={cfg.id}
                className="flex items-start justify-between rounded-lg border bg-white p-4"
              >
                <div className="flex items-start gap-3">
                  <div className={`rounded-lg p-2 ${colorClass}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="font-medium text-stone-800 capitalize">
                      {t(`mode${cfg.mode.charAt(0).toUpperCase() + cfg.mode.slice(1)}`)}
                    </p>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
                      {cfg.question_count && (
                        <span>{t("questions", { count: cfg.question_count })}</span>
                      )}
                      {cfg.time_per_question_override && (
                        <span>
                          {t("timerSecs", { secs: cfg.time_per_question_override })}
                        </span>
                      )}
                      {cfg.category_filter && (
                        <span>{t("category")}: {cfg.category_filter}</span>
                      )}
                      <span>
                        {cfg.show_feedback ? t("showFeedbackOn") : t("showFeedbackOff")}
                      </span>
                    </div>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDeletingId(cfg.id)}
                  className="h-9 w-9 p-0 text-red-500 hover:text-red-700 hover:bg-red-50 shrink-0"
                  aria-label={t("deleteConfig")}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {dialogOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="test-config-title"
        >
          <div
            className="fixed inset-0 bg-black/40"
            onClick={() => { setDialogOpen(false); resetForm(); }}
          />
          <div className="relative z-10 w-full max-w-md rounded-t-xl sm:rounded-xl bg-white p-6 shadow-xl max-h-[90dvh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 id="test-config-title" className="text-lg font-semibold text-stone-900">
                {t("newTestConfig")}
              </h2>
              <button
                onClick={() => { setDialogOpen(false); resetForm(); }}
                className="rounded-md p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
                aria-label={t("cancel")}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-stone-700">
                {t("mode")}
              </label>
              <Select
                value={mode}
                onValueChange={(v) => setMode(v as typeof mode)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exam">{t("modeExam")}</SelectItem>
                  <SelectItem value="training">{t("modeTraining")}</SelectItem>
                  <SelectItem value="review">{t("modeReview")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="block text-sm font-medium text-stone-700">
                  {t("questionCountOptional")}
                </label>
                <input
                  type="number"
                  min={1}
                  value={questionCount}
                  onChange={(e) => setQuestionCount(e.target.value)}
                  placeholder={t("allQuestions")}
                  className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-stone-700">
                  {t("timerOverrideOptional")}
                </label>
                <input
                  type="number"
                  min={1}
                  value={timerOverride}
                  onChange={(e) => setTimerOverride(e.target.value)}
                  placeholder={t("defaultTimer")}
                  className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-stone-700">
                {t("categoryFilterOptional")}
              </label>
              <input
                type="text"
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                placeholder={t("allCategories")}
                className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>

            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="showFeedback"
                checked={showFeedback}
                onChange={(e) => setShowFeedback(e.target.checked)}
                className="h-4 w-4 rounded border-stone-300 text-teal-600 focus:ring-teal-500"
              />
              <label
                htmlFor="showFeedback"
                className="text-sm font-medium text-stone-700 cursor-pointer"
              >
                {t("showFeedback")}
              </label>
            </div>

            {formError && (
              <p className="text-sm text-red-600">{formError}</p>
            )}

            <div className="flex gap-3 pt-2">
              <Button
                onClick={handleCreate}
                disabled={saving}
                className="flex-1 min-h-11 bg-teal-600 hover:bg-teal-700"
              >
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t("createConfig")}
              </Button>
              <Button
                variant="outline"
                onClick={() => { setDialogOpen(false); resetForm(); }}
                disabled={saving}
                className="min-h-11"
              >
                {t("cancel")}
              </Button>
            </div>
          </div>
          </div>
        </div>
      )}

      <AlertDialog
        open={!!deletingId}
        onOpenChange={(open) => { if (!open) setDeletingId(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("confirmDeleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("confirmDeleteConfigDesc")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              disabled={deleting}
              className="bg-red-600 hover:bg-red-700"
            >
              {deleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t("delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
