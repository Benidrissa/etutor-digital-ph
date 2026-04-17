"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useOrg } from "@/components/org/org-context";
import { QBankPdfUpload } from "@/components/qbank/qbank-pdf-upload";
import { QBankQuestionEditor } from "@/components/qbank/qbank-question-editor";
import { QBankTestConfigList } from "@/components/qbank/qbank-test-config";
import {
  getQBankBank,
  listQBankQuestions,
  updateQBankBank,
  type QBankBank,
  type QBankQuestionFull,
} from "@/lib/api";

interface Props {
  bankId: string;
}

const PAGE_SIZE = 20;

const STATUS_KEY: Record<"draft" | "published" | "archived", string> = {
  draft: "statusDraft",
  published: "statusPublished",
  archived: "statusArchived",
};

export function QBankDetailClient({ bankId }: Props) {
  const locale = useLocale();
  const t = useTranslations("qbank");
  const { org } = useOrg();
  const [bank, setBank] = useState<QBankBank | null>(null);
  const [questions, setQuestions] = useState<QBankQuestionFull[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | "all">("all");
  const [publishing, setPublishing] = useState(false);

  async function loadQuestions(p: number = page) {
    const result = await listQBankQuestions(bankId, p, PAGE_SIZE);
    setQuestions(result.questions);
    setTotal(result.total);
    setPage(result.page);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [b, q] = await Promise.all([
          getQBankBank(bankId),
          listQBankQuestions(bankId, 1, PAGE_SIZE),
        ]);
        if (cancelled) return;
        setBank(b);
        setQuestions(q.questions);
        setTotal(q.total);
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bankId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }
  if (error) return <p className="text-sm text-red-700">{error}</p>;
  if (!bank || !org) return null;

  const base = `/${locale}/org/${org.slug}/qbank`;
  const categories = Array.from(
    new Set(questions.map((q) => q.category).filter((c): c is string => Boolean(c)))
  ).sort();
  const visibleQuestions =
    categoryFilter === "all"
      ? questions
      : questions.filter((q) => q.category === categoryFilter);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function togglePublished() {
    if (!bank) return;
    setPublishing(true);
    try {
      const updated = await updateQBankBank(bank.id, {
        status: bank.status === "published" ? "draft" : "published",
      });
      setBank(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="space-y-6">
      <Link
        href={base}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" /> {t("backToBanks")}
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{bank.title}</h1>
            <Badge>{t(STATUS_KEY[bank.status])}</Badge>
          </div>
          {bank.description && (
            <p className="mt-1 text-sm text-muted-foreground">{bank.description}</p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            {t("questionCount", { count: total })} · {t("timePerQSuffix", { seconds: bank.time_per_question_sec })} · {bank.passing_score}% · {bank.language.toUpperCase()}
          </p>
        </div>
        <Button onClick={togglePublished} disabled={publishing} variant="outline">
          {publishing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {bank.status === "published" ? t("unpublish") : t("publish")}
        </Button>
      </header>

      <section className="space-y-3 rounded-lg border bg-white p-4">
        <h2 className="text-lg font-medium">{t("addMoreQuestions")}</h2>
        <QBankPdfUpload
          bankId={bankId}
          onProcessed={(res) => {
            if (res.status === "success") void loadQuestions(1);
          }}
        />
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-medium">{t("questionsHeader")}</h2>
          {categories.length > 0 && (
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="rounded-md border px-3 py-1.5 text-sm"
              aria-label={t("filterByCategory")}
            >
              <option value="all">{t("allCategories")}</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          )}
        </div>

        {visibleQuestions.length === 0 ? (
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t("noQuestionsYet")}
          </p>
        ) : (
          <ul className="space-y-4">
            {visibleQuestions.map((q) => (
              <li key={q.id}>
                <QBankQuestionEditor
                  question={q}
                  onSaved={(updated) =>
                    setQuestions((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
                  }
                  onDeleted={(id) => {
                    setQuestions((prev) => prev.filter((p) => p.id !== id));
                    setTotal((t) => Math.max(0, t - 1));
                  }}
                />
              </li>
            ))}
          </ul>
        )}

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 1}
              onClick={() => void loadQuestions(page - 1)}
            >
              {t("previous")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t("pagePosition", { page, total: totalPages })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => void loadQuestions(page + 1)}
            >
              {t("next")}
            </Button>
          </div>
        )}
      </section>

      <section className="rounded-lg border bg-white p-4">
        <QBankTestConfigList bankId={bankId} />
      </section>
    </div>
  );
}
