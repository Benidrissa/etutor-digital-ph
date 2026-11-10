/**
 * Question card for the story player (format Appendix A.5).
 *
 * The flow A.5 specifies: a wrong answer gets the hint of the matching trap
 * (or the first generic hint), then a second try, then the explanation. Points
 * are 2 on the first try and 1 on the second.
 *
 * The card stays on screen while she answers, and the answer is never revealed
 * before the explanation — the trap hints are written to aim at the specific
 * mistake without giving the result away.
 */

"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { scoreAttempt, seededShuffle, text } from "@/lib/story-course/answer";
import type { Question, Rewards, TextObject } from "@/lib/story-course/types";

/** How a question was answered: enough to show it again, read-only. */
export interface QuestionAnswer {
  /** The last answer given: a choice id, or what was typed. */
  answer: string;
  /** A `multi` question's answer per part. */
  parts?: Record<string, string>;
  correct: boolean;
  points: number;
  attempts: number;
  /**
   * Answered on an earlier visit, which answer is not known here: shown
   * settled, with the right answer and the explanation, and no score.
   */
  unknown?: boolean;
}

/**
 * A question left half-answered: the tries used so far, the hint they
 * earned and the last answer. A card that comes back (Previous, then Next)
 * resumes from it instead of offering a fresh first try (#2688).
 */
export interface QuestionProgress {
  answer: string;
  parts?: Record<string, string>;
  attempts: number;
  hint: TextObject | null;
}

interface QuestionCardProps {
  question: Question;
  /** Language of instruction, then the home language shown beneath it. */
  target: string;
  home: string;
  bilingual: boolean;
  rewards?: Rewards;
  onAnswered: (outcome: { questionId: string } & QuestionAnswer) => void;
  /**
   * Shown again (the story's Previous): the learner's answer and the
   * explanation, settled and read-only. Nothing is scored again.
   */
  review?: QuestionAnswer;
  /** A try already made on this question, to carry on from. */
  resume?: QuestionProgress;
  /** Each try that leaves the question open (a wrong first answer). */
  onProgress?: (progress: QuestionProgress) => void;
  /**
   * Every attempt, right or wrong, as it is checked: the cartoon stage cheers
   * a right one and lets the hero think over a wrong one. `settled` is true
   * when the question is over (right, or the last try used).
   */
  onAttempt?: (outcome: { correct: boolean; settled: boolean }) => void;
  /** Replaces the card's own frame, for a host that draws one around it. */
  className?: string;
}

const SUPERSCRIPT_KEYS = ["²", "³", "⁴"];

function Bilingual({
  value,
  target,
  home,
  bilingual,
  className,
  homeClassName,
}: {
  value?: TextObject | null;
  target: string;
  home: string;
  bilingual: boolean;
  className?: string;
  homeClassName?: string;
}) {
  if (!value) return null;
  const primary = text(value, target, home);
  const secondary = text(value, home, target);
  return (
    <>
      <p className={className}>{primary}</p>
      {bilingual && secondary && secondary !== primary ? (
        <p className={homeClassName ?? "mt-1 text-sm italic text-gray-500"} lang={home}>
          {secondary}
        </p>
      ) : null}
    </>
  );
}

export function QuestionCard({
  question,
  target,
  home,
  bilingual,
  rewards,
  onAnswered,
  onAttempt,
  review,
  resume,
  onProgress,
  className,
}: QuestionCardProps) {
  const t = useTranslations("Story");
  const [typed, setTyped] = useState(review?.answer ?? resume?.answer ?? "");
  const [partAnswers, setPartAnswers] = useState<Record<string, string>>(review?.parts ?? resume?.parts ?? {});
  const [attempts, setAttempts] = useState(review?.attempts ?? resume?.attempts ?? 0);
  const [hint, setHint] = useState<TextObject | null>(review ? null : (resume?.hint ?? null));
  const [notice, setNotice] = useState<string | null>(null);
  const [settled, setSettled] = useState(!!review);
  const [correct, setCorrect] = useState(review?.correct ?? false);
  const [earned, setEarned] = useState(review?.points ?? 0);

  const choices = useMemo(
    () => seededShuffle(question.choices ?? [], question.id),
    [question.choices, question.id],
  );

  const unitLabel = text(rewards?.unit, target, home) || "points";
  const isChoice = question.type === "choice";
  const isMulti = question.type === "multi" && (question.parts?.length ?? 0) > 0;

  const submit = (value: string) => {
    if (settled) return;

    // `multi` carries one answer per part; every part must match.
    if (isMulti) {
      const parts = question.parts ?? [];
      const allCorrect = parts.every((part, index) => {
        const key = part.label ?? String(index);
        const outcome = scoreAttempt(
          partAnswers[key] ?? "",
          { ...question, type: part.type ?? "number", answer: part.answer, traps: [] },
          attempts,
          rewards,
        );
        return outcome.result.correct;
      });
      finish(allCorrect, null, null, value);
      return;
    }

    const outcome = scoreAttempt(value, question, attempts, rewards);
    setNotice(
      outcome.result.decimalCommaUsed
        ? t("useDecimalPoint")
        : outcome.result.needsIndexForm
          ? t("useIndexForm")
          : null,
    );
    finish(outcome.result.correct, outcome.hint, outcome.points, value);
  };

  /**
   * Settle or continue: right answers score, a first wrong answer gets a hint
   * and a second try, a second wrong answer reveals the explanation.
   */
  const finish = (
    isCorrect: boolean,
    nextHint: TextObject | null,
    points: number | null,
    value: string,
  ) => {
    const given = { answer: value, parts: isMulti ? { ...partAnswers } : undefined };
    const nextAttempts = attempts + 1;
    setAttempts(nextAttempts);

    if (isCorrect) {
      const firstTry = rewards?.first_try ?? 2;
      const secondTry = rewards?.second_try ?? 1;
      const fallback =
        nextAttempts === 1 ? firstTry : nextAttempts === 2 ? secondTry : 0;
      const won = points ?? question.points ?? fallback;
      setCorrect(true);
      setSettled(true);
      setEarned(won);
      setHint(null);
      onAnswered({ questionId: question.id, points: won, attempts: nextAttempts, correct: true, ...given });
      onAttempt?.({ correct: true, settled: true });
      return;
    }

    if (nextAttempts >= 2) {
      setSettled(true);
      setHint(null);
      onAnswered({ questionId: question.id, points: 0, attempts: nextAttempts, correct: false, ...given });
      onAttempt?.({ correct: false, settled: true });
      return;
    }

    setHint(nextHint);
    onProgress?.({ ...given, attempts: nextAttempts, hint: nextHint });
    onAttempt?.({ correct: false, settled: false });
  };

  return (
    <section
      className={className ?? "my-5 rounded-xl border-2 border-teal-200 bg-teal-50/40 p-4"}
      aria-live="polite"
    >
      <Bilingual
        value={question.prompt}
        target={target}
        home={home}
        bilingual={bilingual}
        className="font-semibold text-gray-900"
      />

      {question.calculator === false ? (
        <p className="mt-1 text-xs uppercase tracking-wide text-gray-500">{t("noCalculator")}</p>
      ) : null}

      {/* --- input ------------------------------------------------------- */}
      {isChoice ? (
        <ul className="mt-3 space-y-2">
          {choices.map((choice) => {
            const chosen = typed === choice.id;
            const isAnswer = settled && String(question.answer) === choice.id;
            return (
              <li key={choice.id}>
                <button
                  type="button"
                  disabled={settled}
                  onClick={() => {
                    setTyped(choice.id);
                    submit(choice.id);
                  }}
                  className={`min-h-11 w-full rounded-lg border px-4 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:cursor-not-allowed ${
                    isAnswer
                      ? "border-green-600 bg-green-50 font-semibold"
                      : chosen
                        ? "border-teal-600 bg-white"
                        : "border-gray-300 bg-white hover:border-teal-400"
                  }`}
                >
                  {text({ en: choice.en, fr: choice.fr }, target, home)}
                  {settled && chosen ? (
                    <span className="ml-2 text-xs font-semibold uppercase tracking-wide text-gray-600">
                      {`· ${t("yourAnswer")}`}
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : isMulti ? (
        <div className="mt-3 space-y-3">
          {(question.parts ?? []).map((part, index) => {
            const key = part.label ?? String(index);
            return (
              <label key={key} className="block">
                <span className="mr-2 font-mono text-sm text-gray-700">{part.label}</span>
                <input
                  value={partAnswers[key] ?? ""}
                  onChange={(event) =>
                    setPartAnswers((prev) => ({ ...prev, [key]: event.target.value }))
                  }
                  disabled={settled}
                  inputMode="text"
                  className="min-h-11 w-40 rounded-lg border border-gray-300 px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                />
              </label>
            );
          })}
        </div>
      ) : (
        <div className="mt-3">
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submit(typed);
            }}
            disabled={settled}
            inputMode={question.type === "number" ? "decimal" : "text"}
            aria-label={t("yourAnswer")}
            placeholder={question.units ? question.units : undefined}
            className="min-h-11 w-full max-w-xs rounded-lg border border-gray-300 px-3 py-2 text-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          />
          {question.type === "index_form" ? (
            <div className="mt-2 flex gap-2">
              {SUPERSCRIPT_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  disabled={settled}
                  onClick={() => setTyped((prev) => prev + key)}
                  className="min-h-11 min-w-11 rounded-lg border border-gray-300 bg-white text-lg hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                  aria-label={`Insert ${key}`}
                >
                  {key}
                </button>
              ))}
              <button
                type="button"
                disabled={settled}
                onClick={() => setTyped((prev) => prev + " × ")}
                className="min-h-11 min-w-11 rounded-lg border border-gray-300 bg-white text-lg hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                aria-label="Insert times"
              >
                {"×"}
              </button>
            </div>
          ) : null}
        </div>
      )}

      {!isChoice && !settled ? (
        <button
          type="button"
          onClick={() => submit(typed)}
          className="mt-3 min-h-11 rounded-lg bg-teal-600 px-5 font-semibold text-white hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {t("check")}
        </button>
      ) : null}

      {/* --- feedback ---------------------------------------------------- */}
      {notice ? <p className="mt-2 text-sm text-amber-700">{notice}</p> : null}

      {hint ? (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">{t("hint")}</p>
          <Bilingual
            value={hint}
            target={target}
            home={home}
            bilingual={bilingual}
            className="text-sm text-amber-900"
            homeClassName="mt-1 text-sm italic text-amber-700"
          />
        </div>
      ) : null}

      {settled ? (
        <div className="mt-3">
          <p className={`font-semibold ${correct ? "text-green-700" : "text-gray-800"}`}>
            {correct && !review?.unknown ? `+${earned} ${unitLabel}` : t("howItWorks")}
          </p>
          {question.explanation ? (
            <div className="mt-2 rounded-lg border border-gray-200 bg-white p-3">
              <Bilingual
                value={question.explanation}
                target={target}
                home={home}
                bilingual={bilingual}
                className="text-sm text-gray-800"
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
