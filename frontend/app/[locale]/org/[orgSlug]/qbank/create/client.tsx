"use client";

import { useState } from "react";
import { useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrg } from "@/components/org/org-context";
import { QBankPdfUpload } from "@/components/qbank/qbank-pdf-upload";
import { createQBankBank, type QBankBank, type QBankType } from "@/lib/api";

const BANK_TYPES: { value: QBankType; label: string }[] = [
  { value: "driving", label: "Driving school" },
  { value: "exam_prep", label: "Exam prep" },
  { value: "psychotechnic", label: "Psychotechnic" },
  { value: "general_culture", label: "General culture" },
];

export function QBankCreateClient() {
  const locale = useLocale();
  const router = useRouter();
  const { org } = useOrg();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bank, setBank] = useState<QBankBank | null>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [bankType, setBankType] = useState<QBankType>("driving");
  const [language, setLanguage] = useState("fr");
  const [timePerQuestion, setTimePerQuestion] = useState(25);
  const [passingScore, setPassingScore] = useState(80);

  if (!org) return null;
  const base = `/${locale}/org/${org.slug}/qbank`;

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createQBankBank({
        organization_id: org.id,
        title,
        description: description || null,
        bank_type: bankType,
        language,
        time_per_question_sec: timePerQuestion,
        passing_score: passingScore,
      });
      setBank(created);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create bank");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link
        href={base}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" /> Back to banks
      </Link>
      <h1 className="text-2xl font-semibold">Create question bank</h1>

      {!bank ? (
        <form onSubmit={handleCreate} className="space-y-4 rounded-lg border bg-white p-5">
          <div className="space-y-2">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              minLength={2}
              maxLength={500}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="type">Type</Label>
              <select
                id="type"
                value={bankType}
                onChange={(e) => setBankType(e.target.value as QBankType)}
                className="w-full rounded-md border px-3 py-2 text-sm"
              >
                {BANK_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="language">Language</Label>
              <select
                id="language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-md border px-3 py-2 text-sm"
              >
                <option value="fr">Français</option>
                <option value="en">English</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="time">Time per question (seconds)</Label>
              <Input
                id="time"
                type="number"
                min={5}
                max={120}
                value={timePerQuestion}
                onChange={(e) => setTimePerQuestion(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="passing">Passing score (%)</Label>
              <Input
                id="passing"
                type="number"
                min={0}
                max={100}
                value={passingScore}
                onChange={(e) => setPassingScore(Number(e.target.value))}
              />
            </div>
          </div>

          {error && <p className="text-sm text-red-700">{error}</p>}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => router.push(base)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create bank
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-4 rounded-lg border bg-white p-5">
          <p className="text-sm">
            Bank <span className="font-medium">{bank.title}</span> created. Now upload a PDF to
            extract questions.
          </p>
          <QBankPdfUpload
            bankId={bank.id}
            onProcessed={(res) => {
              if (res.status === "success") {
                setTimeout(() => router.push(`${base}/${bank.id}`), 1500);
              }
            }}
          />
          <div className="flex justify-end">
            <Button onClick={() => router.push(`${base}/${bank.id}`)}>Open bank</Button>
          </div>
        </div>
      )}
    </div>
  );
}
