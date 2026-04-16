"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { useOrg } from "@/components/org/org-context";
import { fetchQBank } from "@/lib/api";
import type { QBankResponse } from "@/lib/api";
import { ArrowLeft, Loader2, BookOpen, Settings2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QBankQuestionList } from "@/components/qbank/qbank-question-list";
import { QBankTestConfigSection } from "@/components/qbank/qbank-test-config";
import { QBankPdfUpload } from "@/components/qbank/qbank-pdf-upload";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-stone-100 text-stone-600",
  published: "bg-green-100 text-green-700",
  archived: "bg-amber-100 text-amber-700",
};

type Tab = "questions" | "tests";

export default function QBankDetailPage() {
  const t = useTranslations("QBank");
  const locale = useLocale();
  const { bankId } = useParams<{ bankId: string }>();
  const { org, orgId } = useOrg();
  const [bank, setBank] = useState<QBankResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("questions");
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [questionRefreshKey, setQuestionRefreshKey] = useState(0);

  useEffect(() => {
    if (!orgId || !bankId) return;
    fetchQBank(orgId, bankId)
      .then(setBank)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [orgId, bankId]);

  if (!org) return null;

  const base = `/${locale}/org/${org.slug}/qbank`;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-teal-600" />
      </div>
    );
  }

  if (!bank) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild className="min-h-11 min-w-11 p-0">
          <Link href={base}>
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>
        <div className="rounded-lg border bg-white p-12 text-center">
          <p className="text-stone-500">{t("bankNotFound")}</p>
        </div>
      </div>
    );
  }

  const handleUploadComplete = () => {
    setUploadDialogOpen(false);
    setQuestionRefreshKey((k) => k + 1);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3">
        <Button
          variant="ghost"
          asChild
          className="mt-1 min-h-11 min-w-11 p-0 shrink-0"
          aria-label={t("back")}
        >
          <Link href={base}>
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-stone-900 truncate">
              {bank.title}
            </h1>
            <span
              className={`inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                STATUS_COLORS[bank.status]
              }`}
            >
              {t(`status${bank.status.charAt(0).toUpperCase() + bank.status.slice(1)}`)}
            </span>
          </div>
          <p className="mt-1 text-sm text-stone-500">
            {bank.bank_type} · {t("questionsCount", { count: bank.question_count })} ·{" "}
            {bank.language.toUpperCase()} · {t("passingScoreLabel")}: {bank.passing_score}%
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setUploadDialogOpen(true)}
          className="min-h-11 shrink-0"
        >
          <Upload className="mr-2 h-4 w-4" />
          {t("uploadMorePdf")}
        </Button>
      </div>

      <div className="flex gap-1 border-b overflow-x-auto">
        {(["questions", "tests"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeTab === tab
                ? "border-teal-600 text-teal-700"
                : "border-transparent text-stone-500 hover:text-stone-800 hover:border-stone-300"
            }`}
          >
            {tab === "questions" ? (
              <BookOpen className="h-4 w-4" />
            ) : (
              <Settings2 className="h-4 w-4" />
            )}
            {t(tab === "questions" ? "tabQuestions" : "tabTests")}
          </button>
        ))}
      </div>

      {activeTab === "questions" && (
        <QBankQuestionList
          orgId={orgId!}
          bankId={bankId}
          refreshKey={questionRefreshKey}
        />
      )}

      {activeTab === "tests" && (
        <QBankTestConfigSection orgId={orgId!} bankId={bankId} />
      )}

      {uploadDialogOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="upload-pdf-title"
        >
          <div
            className="fixed inset-0 bg-black/40"
            onClick={() => setUploadDialogOpen(false)}
          />
          <div className="relative z-10 w-full max-w-lg rounded-t-xl sm:rounded-xl bg-white p-6 shadow-xl max-h-[90dvh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 id="upload-pdf-title" className="text-lg font-semibold text-stone-900">
                {t("uploadMorePdf")}
              </h2>
              <button
                onClick={() => setUploadDialogOpen(false)}
                className="rounded-md p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
                aria-label={t("cancel")}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <QBankPdfUpload
              orgId={orgId!}
              bankId={bankId}
              onComplete={handleUploadComplete}
            />
          </div>
        </div>
      )}
    </div>
  );
}
