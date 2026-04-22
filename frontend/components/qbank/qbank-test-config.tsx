"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createQBankTest,
  listQBankTests,
  type QBankTestConfig,
  type QBankTestMode,
} from "@/lib/api";

interface Props {
  bankId: string;
  canEdit?: boolean;
}

const MODES: { value: QBankTestMode; key: string }[] = [
  { value: "exam", key: "modeExam" },
  { value: "training", key: "modeTraining" },
  { value: "review", key: "modeReview" },
];

export function QBankTestConfigList({ bankId, canEdit = true }: Props) {
  const t = useTranslations("qbank");
  const [tests, setTests] = useState<QBankTestConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<QBankTestMode>("exam");
  const [count, setCount] = useState<number | "">("");
  const [shuffle, setShuffle] = useState(true);
  const [timeOverride, setTimeOverride] = useState<number | "">("");
  const [showFeedback, setShowFeedback] = useState(false);

  useEffect(() => {
    listQBankTests(bankId)
      .then(setTests)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [bankId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const created = await createQBankTest({
        question_bank_id: bankId,
        title,
        mode,
        question_count: count === "" ? null : Number(count),
        shuffle_questions: shuffle,
        time_per_question_sec: timeOverride === "" ? null : Number(timeOverride),
        show_feedback: showFeedback,
      });
      setTests((prev) => [...prev, created]);
      setTitle("");
      setCount("");
      setTimeOverride("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">{t("testsHeader")}</h2>
      {loading ? (
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      ) : tests.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("noTests")}</p>
      ) : (
        <ul className="space-y-2">
          {tests.map((test) => (
            <li
              key={test.id}
              className="flex items-center justify-between gap-3 rounded-md border bg-white p-3 text-sm"
            >
              <div>
                <span className="font-medium">{test.title}</span>
                <span className="ml-2 text-xs uppercase text-muted-foreground">{test.mode}</span>
              </div>
              <span className="text-xs text-muted-foreground">
                {test.question_count ?? "all"} q · {test.time_per_question_sec ?? "default"} s · {test.shuffle_questions ? "shuffled" : "ordered"}
              </span>
            </li>
          ))}
        </ul>
      )}

      {canEdit && <form onSubmit={handleCreate} className="space-y-3 rounded-md border bg-gray-50 p-4">
        <h3 className="text-sm font-medium">{t("newTest")}</h3>

        <div className="space-y-2">
          <Label htmlFor="test-title">{t("fieldTitle")}</Label>
          <Input
            id="test-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            minLength={2}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="test-mode">{t("fieldMode")}</Label>
            <select
              id="test-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as QBankTestMode)}
              className="w-full rounded-md border px-3 py-2 text-sm"
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {t(m.key)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="test-count">{t("fieldQuestionCount")}</Label>
            <Input
              id="test-count"
              type="number"
              min={1}
              max={500}
              value={count}
              onChange={(e) => setCount(e.target.value === "" ? "" : Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="test-time">{t("fieldTimeOverride")}</Label>
            <Input
              id="test-time"
              type="number"
              min={5}
              max={120}
              value={timeOverride}
              onChange={(e) =>
                setTimeOverride(e.target.value === "" ? "" : Number(e.target.value))
              }
            />
          </div>
          <div className="flex flex-col justify-end gap-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={shuffle}
                onChange={(e) => setShuffle(e.target.checked)}
              />
              {t("shuffleQuestions")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={showFeedback}
                onChange={(e) => setShowFeedback(e.target.checked)}
              />
              {t("showFeedback")}
            </label>
          </div>
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

        <div className="flex justify-end">
          <Button type="submit" disabled={creating}>
            {creating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-2 h-4 w-4" />
            )}
            {t("createTest")}
          </Button>
        </div>
      </form>}
    </div>
  );
}
