"use client";

import { useEffect, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Pencil, Trash2, ImageIcon, Loader2, ChevronLeft, ChevronRight, X } from "lucide-react";
import { fetchQBankQuestions, deleteQBankQuestion } from "@/lib/api";
import type { QBankQuestion } from "@/lib/api";
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
import { Badge } from "@/components/ui/badge";
import { QBankQuestionEditor } from "./qbank-question-editor";

const PAGE_SIZE = 20;

interface QBankQuestionListProps {
  orgId: string;
  bankId: string;
  refreshKey?: number;
}

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: "bg-green-100 text-green-700",
  medium: "bg-amber-100 text-amber-700",
  hard: "bg-red-100 text-red-700",
};

export function QBankQuestionList({
  orgId,
  bankId,
  refreshKey = 0,
}: QBankQuestionListProps) {
  const t = useTranslations("QBank");
  const [questions, setQuestions] = useState<QBankQuestion[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [filterDifficulty, setFilterDifficulty] = useState<string>("");
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [editingQuestion, setEditingQuestion] = useState<QBankQuestion | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setLoading(true);
    fetchQBankQuestions(orgId, bankId, {
      difficulty: filterDifficulty || undefined,
      category: filterCategory || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    })
      .then((res) => {
        setQuestions(res.questions);
        setTotal(res.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [orgId, bankId, filterDifficulty, filterCategory, page]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  useEffect(() => {
    setPage(0);
  }, [filterDifficulty, filterCategory]);

  const handleSaved = (updated: QBankQuestion) => {
    setQuestions((prev) => prev.map((q) => (q.id === updated.id ? updated : q)));
    setEditingQuestion(null);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingId) return;
    setDeleting(true);
    try {
      await deleteQBankQuestion(orgId, bankId, deletingId);
      setQuestions((prev) => prev.filter((q) => q.id !== deletingId));
      setTotal((prev) => prev - 1);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(deletingId);
        return next;
      });
    } catch {
    } finally {
      setDeleting(false);
      setDeletingId(null);
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={filterDifficulty || "all"}
          onValueChange={(v) => setFilterDifficulty(v === "all" ? "" : v)}
        >
          <SelectTrigger className="w-36">
            <SelectValue placeholder={t("allDifficulties")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allDifficulties")}</SelectItem>
            <SelectItem value="easy">{t("difficultyEasy")}</SelectItem>
            <SelectItem value="medium">{t("difficultyMedium")}</SelectItem>
            <SelectItem value="hard">{t("difficultyHard")}</SelectItem>
          </SelectContent>
        </Select>

        <input
          type="text"
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          placeholder={t("filterByCategory")}
          className="rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 w-44"
        />

        <span className="ml-auto text-sm text-stone-500">
          {t("questionCount", { count: total })}
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-teal-600" />
        </div>
      ) : questions.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center">
          <p className="text-stone-500">{t("noQuestions")}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {questions.map((q) => (
              <div
                key={q.id}
                className={`relative rounded-lg border bg-white shadow-sm transition-shadow hover:shadow-md ${
                  selectedIds.has(q.id) ? "ring-2 ring-teal-500" : ""
                }`}
              >
                <div
                  className="absolute top-2 left-2 z-10"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    aria-label={t("selectQuestion")}
                    checked={selectedIds.has(q.id)}
                    onChange={() => toggleSelect(q.id)}
                    className="h-4 w-4 rounded border-stone-300 text-teal-600 focus:ring-teal-500"
                  />
                </div>

                {q.image_url ? (
                  <div className="h-36 overflow-hidden rounded-t-lg bg-stone-100">
                    <img
                      src={q.image_url}
                      alt={t("questionImage")}
                      className="h-full w-full object-contain"
                    />
                  </div>
                ) : (
                  <div className="flex h-36 items-center justify-center rounded-t-lg bg-stone-100">
                    <ImageIcon className="h-10 w-10 text-stone-300" aria-hidden="true" />
                  </div>
                )}

                <div className="p-3 space-y-2">
                  <p className="line-clamp-3 text-sm text-stone-800 leading-snug">
                    {q.question_text}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        DIFFICULTY_COLORS[q.difficulty] ?? "bg-stone-100 text-stone-600"
                      }`}
                    >
                      {t(`difficulty${q.difficulty.charAt(0).toUpperCase() + q.difficulty.slice(1)}`)}
                    </span>
                    {q.category && (
                      <Badge variant="outline" className="text-xs">
                        {q.category}
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-end gap-1 border-t px-3 py-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditingQuestion(q)}
                    className="h-8 w-8 p-0"
                    aria-label={t("editQuestion")}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeletingId(q.id)}
                    className="h-8 w-8 p-0 text-red-500 hover:text-red-700 hover:bg-red-50"
                    aria-label={t("deleteQuestion")}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="min-h-11 min-w-11"
                aria-label={t("previousPage")}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm text-stone-600">
                {t("pageOf", { page: page + 1, total: totalPages })}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="min-h-11 min-w-11"
                aria-label={t("nextPage")}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </>
      )}

      {editingQuestion && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-question-title"
        >
          <div
            className="fixed inset-0 bg-black/40"
            onClick={() => setEditingQuestion(null)}
          />
          <div className="relative z-10 w-full max-w-lg rounded-t-xl sm:rounded-xl bg-white p-6 shadow-xl max-h-[90dvh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 id="edit-question-title" className="text-lg font-semibold text-stone-900">
                {t("editQuestion")}
              </h2>
              <button
                onClick={() => setEditingQuestion(null)}
                className="rounded-md p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
                aria-label={t("cancel")}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <QBankQuestionEditor
              question={editingQuestion}
              orgId={orgId}
              bankId={bankId}
              onSaved={handleSaved}
              onCancel={() => setEditingQuestion(null)}
            />
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
              {t("confirmDeleteDesc")}
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
