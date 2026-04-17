"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  deleteQBankQuestion,
  updateQBankQuestion,
  type QBankDifficulty,
  type QBankQuestionFull,
} from "@/lib/api";

interface Props {
  question: QBankQuestionFull;
  onSaved: (updated: QBankQuestionFull) => void;
  onDeleted: (id: string) => void;
}

const DIFFICULTIES: QBankDifficulty[] = ["easy", "medium", "hard"];

export function QBankQuestionEditor({ question, onSaved, onDeleted }: Props) {
  const t = useTranslations("qbank");
  const [text, setText] = useState(question.question_text);
  const [options, setOptions] = useState([...question.options]);
  const [correct, setCorrect] = useState<number[]>([...question.correct_answer_indices]);
  const [category, setCategory] = useState(question.category ?? "");
  const [difficulty, setDifficulty] = useState<QBankDifficulty>(question.difficulty);
  const [explanation, setExplanation] = useState(question.explanation ?? "");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(question.question_text);
    setOptions([...question.options]);
    setCorrect([...question.correct_answer_indices]);
    setCategory(question.category ?? "");
    setDifficulty(question.difficulty);
    setExplanation(question.explanation ?? "");
    setDirty(false);
  }, [question]);

  function touch() {
    setDirty(true);
  }

  function toggleCorrect(idx: number) {
    setCorrect((prev) =>
      prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx].sort()
    );
    touch();
  }

  function updateOption(idx: number, value: string) {
    setOptions((prev) => prev.map((o, i) => (i === idx ? value : o)));
    touch();
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateQBankQuestion(question.id, {
        question_text: text,
        options,
        correct_answer_indices: correct,
        category: category || null,
        difficulty,
        explanation: explanation || null,
      });
      onSaved(updated);
      setDirty(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(t("confirmDeleteQuestion"))) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteQBankQuestion(question.id);
      onDeleted(question.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-4 rounded-lg border bg-white p-4">
      {question.image_url && (
        <div className="relative aspect-video w-full overflow-hidden rounded-md bg-gray-50">
          <Image
            src={question.image_url}
            alt={`Question ${question.order_index}`}
            fill
            className="object-contain"
            sizes="(max-width: 768px) 100vw, 60vw"
            unoptimized
          />
        </div>
      )}

      <div className="space-y-2">
        <Label>{t("fieldQuestion")}</Label>
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            touch();
          }}
          rows={2}
          className="w-full rounded-md border px-3 py-2 text-sm"
        />
      </div>

      <div className="space-y-2">
        <Label>{t("fieldOptions")}</Label>
        {options.map((opt, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={correct.includes(idx)}
              onChange={() => toggleCorrect(idx)}
              className="h-4 w-4"
              aria-label={`Option ${String.fromCharCode(65 + idx)} correct`}
            />
            <span className="w-6 text-sm font-medium">{String.fromCharCode(65 + idx)}.</span>
            <Input value={opt} onChange={(e) => updateOption(idx, e.target.value)} />
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`cat-${question.id}`}>{t("fieldCategory")}</Label>
          <Input
            id={`cat-${question.id}`}
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              touch();
            }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`diff-${question.id}`}>{t("fieldDifficulty")}</Label>
          <select
            id={`diff-${question.id}`}
            value={difficulty}
            onChange={(e) => {
              setDifficulty(e.target.value as QBankDifficulty);
              touch();
            }}
            className="w-full rounded-md border px-3 py-2 text-sm"
          >
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={`exp-${question.id}`}>{t("fieldExplanation")}</Label>
        <textarea
          id={`exp-${question.id}`}
          value={explanation}
          onChange={(e) => {
            setExplanation(e.target.value);
            touch();
          }}
          rows={2}
          className="w-full rounded-md border px-3 py-2 text-sm"
        />
      </div>

      {error && <p className="text-sm text-red-700">{error}</p>}

      <div className="flex justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={handleDelete}
          disabled={deleting || saving}
        >
          {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
          {t("delete")}
        </Button>
        <Button type="button" onClick={handleSave} disabled={!dirty || saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t("saveChanges")}
        </Button>
      </div>
    </div>
  );
}
