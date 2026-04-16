"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, X, Loader2 } from "lucide-react";
import { updateQBankQuestion } from "@/lib/api";
import type { QBankQuestion, QuestionDifficulty } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface QBankQuestionEditorProps {
  question: QBankQuestion;
  orgId: string;
  bankId: string;
  onSaved: (updated: QBankQuestion) => void;
  onCancel: () => void;
}

export function QBankQuestionEditor({
  question,
  orgId,
  bankId,
  onSaved,
  onCancel,
}: QBankQuestionEditorProps) {
  const t = useTranslations("QBank");
  const [questionText, setQuestionText] = useState(question.question_text);
  const [options, setOptions] = useState(question.options.map((o) => ({ ...o })));
  const [correctAnswer, setCorrectAnswer] = useState(question.correct_answer);
  const [category, setCategory] = useState(question.category ?? "");
  const [difficulty, setDifficulty] = useState<QuestionDifficulty>(question.difficulty);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOptionTextChange = (idx: number, text: string) => {
    setOptions((prev) => prev.map((o, i) => (i === idx ? { ...o, text } : o)));
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const updated = await updateQBankQuestion(orgId, bankId, question.id, {
        question_text: questionText,
        options,
        correct_answer: correctAnswer,
        category: category || undefined,
        difficulty,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {question.image_url && (
        <div className="rounded-lg overflow-hidden border bg-stone-50">
          <img
            src={question.image_url}
            alt={t("questionImage")}
            className="w-full object-contain max-h-64"
          />
        </div>
      )}

      <div className="space-y-2">
        <label className="block text-sm font-medium text-stone-700">
          {t("questionText")}
        </label>
        <textarea
          value={questionText}
          onChange={(e) => setQuestionText(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none min-h-[80px]"
          placeholder={t("questionTextPlaceholder")}
        />
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-stone-700">{t("options")}</p>
        {options.map((opt, idx) => (
          <div key={opt.key} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setCorrectAnswer(opt.key)}
              aria-label={t("markCorrect", { key: opt.key })}
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors ${
                correctAnswer === opt.key
                  ? "border-green-500 bg-green-500 text-white"
                  : "border-stone-300 bg-white text-stone-600 hover:border-teal-400"
              }`}
            >
              {opt.key}
            </button>
            <input
              type="text"
              value={opt.text}
              onChange={(e) => handleOptionTextChange(idx, e.target.value)}
              className="flex-1 rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              placeholder={`${t("option")} ${opt.key}`}
            />
            {correctAnswer === opt.key && (
              <Check className="h-4 w-4 text-green-600 shrink-0" />
            )}
          </div>
        ))}
        <p className="text-xs text-stone-500">{t("clickCircleToMarkCorrect")}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <label className="block text-sm font-medium text-stone-700">
            {t("category")}
          </label>
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
            placeholder={t("categoryPlaceholder")}
          />
        </div>

        <div className="space-y-2">
          <label className="block text-sm font-medium text-stone-700">
            {t("difficulty")}
          </label>
          <Select
            value={difficulty}
            onValueChange={(v) => setDifficulty(v as QuestionDifficulty)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="easy">{t("difficultyEasy")}</SelectItem>
              <SelectItem value="medium">{t("difficultyMedium")}</SelectItem>
              <SelectItem value="hard">{t("difficultyHard")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2">
          <X className="h-4 w-4 text-red-600 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <div className="flex gap-3 pt-2">
        <Button
          onClick={handleSave}
          disabled={saving}
          className="min-h-11 flex-1 bg-teal-600 hover:bg-teal-700"
        >
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t("save")}
        </Button>
        <Button
          variant="outline"
          onClick={onCancel}
          disabled={saving}
          className="min-h-11"
        >
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
