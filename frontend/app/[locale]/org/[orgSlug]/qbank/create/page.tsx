"use client";

import { useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useOrg } from "@/components/org/org-context";
import { createQBank } from "@/lib/api";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { QBankPdfUpload } from "@/components/qbank/qbank-pdf-upload";

const BANK_TYPES = [
  "driving",
  "exam_prep",
  "certification",
  "placement",
  "other",
];

const LANGUAGES = [
  { value: "fr", label: "Français" },
  { value: "en", label: "English" },
];

export default function CreateQBankPage() {
  const t = useTranslations("QBank");
  const locale = useLocale();
  const router = useRouter();
  const { org, orgId } = useOrg();

  const [title, setTitle] = useState("");
  const [bankType, setBankType] = useState("exam_prep");
  const [language, setLanguage] = useState("fr");
  const [timePerQuestion, setTimePerQuestion] = useState("60");
  const [passingScore, setPassingScore] = useState("70");
  const [createdBankId, setCreatedBankId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  if (!org) return null;

  const base = `/${locale}/org/${org.slug}/qbank`;

  const validate = () => {
    const errs: Record<string, string> = {};
    if (!title.trim()) errs.title = t("titleRequired");
    const tpq = parseInt(timePerQuestion, 10);
    if (isNaN(tpq) || tpq < 1) errs.timePerQuestion = t("mustBePositive");
    const ps = parseInt(passingScore, 10);
    if (isNaN(ps) || ps < 0 || ps > 100) errs.passingScore = t("mustBe0To100");
    return errs;
  };

  const handleCreate = async () => {
    const errs = validate();
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      return;
    }
    setFieldErrors({});
    setError(null);
    setSaving(true);
    try {
      const bank = await createQBank(orgId!, {
        title: title.trim(),
        bank_type: bankType,
        language,
        time_per_question: parseInt(timePerQuestion, 10),
        passing_score: parseInt(passingScore, 10),
      });
      setCreatedBankId(bank.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  const handleUploadComplete = () => {
    router.push(`${base}/${createdBankId}`);
  };

  const handleSkipUpload = () => {
    router.push(`${base}/${createdBankId}`);
  };

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          asChild
          className="min-h-11 min-w-11 p-0"
          aria-label={t("back")}
        >
          <Link href={base}>
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>
        <h1 className="text-2xl font-bold text-stone-900">{t("createBank")}</h1>
      </div>

      {!createdBankId ? (
        <div className="rounded-lg border bg-white p-6 space-y-5 shadow-sm">
          <div className="space-y-2">
            <label
              htmlFor="bank-title"
              className="block text-sm font-medium text-stone-700"
            >
              {t("bankTitle")} <span className="text-red-500">*</span>
            </label>
            <input
              id="bank-title"
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (fieldErrors.title) setFieldErrors((p) => ({ ...p, title: "" }));
              }}
              placeholder={t("bankTitlePlaceholder")}
              className={`w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 ${
                fieldErrors.title ? "border-red-400" : "border-stone-300"
              }`}
            />
            {fieldErrors.title && (
              <p className="text-xs text-red-600">{fieldErrors.title}</p>
            )}
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-stone-700">
              {t("bankType")} <span className="text-red-500">*</span>
            </label>
            <Select value={bankType} onValueChange={setBankType}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BANK_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {t(`bankType_${type}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-stone-700">
              {t("language")} <span className="text-red-500">*</span>
            </label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGES.map((l) => (
                  <SelectItem key={l.value} value={l.value}>
                    {l.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                htmlFor="time-per-question"
                className="block text-sm font-medium text-stone-700"
              >
                {t("timePerQuestion")}
              </label>
              <div className="relative">
                <input
                  id="time-per-question"
                  type="number"
                  min={1}
                  value={timePerQuestion}
                  onChange={(e) => {
                    setTimePerQuestion(e.target.value);
                    if (fieldErrors.timePerQuestion)
                      setFieldErrors((p) => ({ ...p, timePerQuestion: "" }));
                  }}
                  className={`w-full rounded-md border px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 ${
                    fieldErrors.timePerQuestion ? "border-red-400" : "border-stone-300"
                  }`}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-stone-400">
                  {t("seconds")}
                </span>
              </div>
              {fieldErrors.timePerQuestion && (
                <p className="text-xs text-red-600">{fieldErrors.timePerQuestion}</p>
              )}
            </div>

            <div className="space-y-2">
              <label
                htmlFor="passing-score"
                className="block text-sm font-medium text-stone-700"
              >
                {t("passingScore")}
              </label>
              <div className="relative">
                <input
                  id="passing-score"
                  type="number"
                  min={0}
                  max={100}
                  value={passingScore}
                  onChange={(e) => {
                    setPassingScore(e.target.value);
                    if (fieldErrors.passingScore)
                      setFieldErrors((p) => ({ ...p, passingScore: "" }));
                  }}
                  className={`w-full rounded-md border px-3 py-2 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 ${
                    fieldErrors.passingScore ? "border-red-400" : "border-stone-300"
                  }`}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-stone-400">
                  %
                </span>
              </div>
              {fieldErrors.passingScore && (
                <p className="text-xs text-red-600">{fieldErrors.passingScore}</p>
              )}
            </div>
          </div>

          {error && (
            <p className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-600">
              {error}
            </p>
          )}

          <Button
            onClick={handleCreate}
            disabled={saving}
            className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
          >
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t("createAndContinue")}
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border bg-white p-6 space-y-5 shadow-sm">
          <div>
            <h2 className="text-lg font-semibold text-stone-900">{t("uploadPdf")}</h2>
            <p className="mt-1 text-sm text-stone-500">{t("uploadPdfDesc")}</p>
          </div>

          <QBankPdfUpload
            orgId={orgId!}
            bankId={createdBankId}
            onComplete={handleUploadComplete}
          />

          <div className="pt-2 border-t">
            <Button
              variant="ghost"
              onClick={handleSkipUpload}
              className="w-full min-h-11 text-stone-600"
            >
              {t("skipUpload")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
