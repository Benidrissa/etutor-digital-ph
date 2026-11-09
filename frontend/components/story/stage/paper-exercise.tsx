/**
 * A paper-and-pen exercise (A.6).
 *
 * Photo checking needs a camera and the AI relay, which this slice does not
 * wire up. Until then the exercise is done on paper and the learner marks it
 * herself: "Done on paper" opens the worked answer and its mark scheme, then
 * "I got it" awards the exercise's marks and "Not yet" awards none. The
 * validator counts every exercise's marks into `checks.max_points` (contract
 * X6), so without the self-mark no story with an exercise could reach a full
 * score. All of it works offline.
 */

"use client";

import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { text } from "@/lib/story-course/answer";
import type { Exercise } from "@/lib/story-course/types";

export function PaperExercise({
  exercise,
  label,
  target,
  home,
  bilingual,
  settled,
  onMarked,
}: {
  exercise: Exercise;
  /** The exercise's name for the learner (its id, without a module namespace). */
  label: string;
  target: string;
  home: string;
  bilingual: boolean;
  settled: boolean;
  onMarked: (points: number) => void;
}) {
  const t = useTranslations("Story");
  // "Done on paper" pressed: the worked answer is open and can be marked.
  const [opened, setOpened] = useState(false);
  const [showWorking, setShowWorking] = useState(true);
  const [awarded, setAwarded] = useState<number | null>(null);
  const promptId = useId();
  const working = exercise.working ?? {};
  const marks = Math.max(0, Number(exercise.marks) || 0);
  const open = opened || settled;

  const mark = (points: number) => {
    if (settled || awarded !== null) return;
    setAwarded(points);
    onMarked(points);
  };

  return (
    <section className="my-2 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50/90 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-600">
        {[
          t("onPaper"),
          label,
          t("part", { part: exercise.part }),
          exercise.marks ? `[${exercise.marks}]` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <p className="mt-2 font-medium text-gray-900">{text(exercise.prompt, target, home)}</p>
      {bilingual ? (
        <p className="mt-1 text-sm italic text-gray-600" lang={home}>
          {text(exercise.prompt, home, target)}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        {!open ? (
          <button
            type="button"
            onClick={() => setOpened(true)}
            className="min-h-11 rounded-lg bg-gray-800 px-4 font-semibold text-white hover:bg-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-700"
          >
            {t("doneOnPaper")}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setShowWorking((on) => !on)}
            aria-expanded={showWorking}
            className="min-h-11 rounded-lg border border-gray-400 bg-white px-4 font-semibold text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-700"
          >
            {showWorking ? t("hideWorking") : t("showWorking")}
          </button>
        )}
      </div>

      {open && showWorking ? (
        <div className="mt-3 rounded-lg border border-gray-200 bg-white p-3">
          <ol className="space-y-1 font-mono text-sm text-gray-800">
            {(working[target] ?? working[home] ?? []).map((row, index) => (
              <li key={index}>{row}</li>
            ))}
          </ol>
          {exercise.mark_scheme?.length ? (
            <ul className="mt-3 space-y-1 text-sm">
              {exercise.mark_scheme.map((row, index) => (
                <li key={index}>
                  <span className="mr-2 font-mono font-semibold text-teal-700">{row.code}</span>
                  {text({ en: row.en, fr: row.fr }, target, home)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {open && !settled ? (
        <div className="mt-3" role="group" aria-labelledby={promptId}>
          <p id={promptId} className="text-sm font-medium text-gray-800">
            {t("selfMarkPrompt")}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => mark(marks)}
              className="min-h-11 rounded-lg bg-teal-600 px-4 font-semibold text-white hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              {t("selfMarkGotIt")}
              {marks ? <span className="font-normal">{` (+${marks})`}</span> : null}
            </button>
            <button
              type="button"
              onClick={() => mark(0)}
              className="min-h-11 rounded-lg border border-gray-400 bg-white px-4 font-semibold text-gray-800 hover:border-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-700"
            >
              {t("selfMarkNotYet")}
            </button>
          </div>
        </div>
      ) : null}

      {settled && awarded !== null && marks > 0 ? (
        <p className="mt-3 text-sm font-semibold text-teal-700" role="status">
          {t("selfMarked", { points: awarded, marks })}
        </p>
      ) : null}
    </section>
  );
}
