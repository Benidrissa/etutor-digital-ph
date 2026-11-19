/**
 * The bet of a beat (#2711): predict, observe, name.
 *
 * `BetCard` is the prediction itself: an ungraded question with two or three
 * chips, the stimulus in view, no points and no right or wrong said. `BetDemo`
 * is what follows: the demo the learner acts on, then the bet put next to what
 * it showed, in a polite live region. A bet is an `ask` that an older player
 * plays as a plain multiple-choice question (it has `points: 0`), so nothing
 * here may be needed to read a stored story.
 */

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { text } from "@/lib/story-course/answer";
import type { Question } from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { StimulusThumb } from "./stimulus-thumb";

export function BetCard({
  question,
  target,
  home,
  bilingual,
  lang,
  chosen,
  locked = false,
  onBet,
}: {
  question: Question;
  target: string;
  home: string;
  bilingual: boolean;
  lang: "fr" | "en";
  /** The chip already picked (the card seen again with Previous). */
  chosen?: string;
  /** Seen again, not to be changed. */
  locked?: boolean;
  onBet: (choiceId: string) => void;
}) {
  const t = useTranslations("Story");
  const [picked, setPicked] = useState<string | undefined>(chosen);
  const choices = question.choices ?? [];
  return (
    <section className="pt-2" aria-label={t("betBanner")}>
      <StimulusThumb stimulus={question.stimulus} lang={lang} />
      <p className="font-semibold text-gray-900">{text(question.prompt, target, home)}</p>
      {bilingual && text(question.prompt, home, target) !== text(question.prompt, target, home) ? (
        <p className="mt-1 text-sm italic text-gray-500" lang={home}>
          {text(question.prompt, home, target)}
        </p>
      ) : null}
      <p className="mt-1 text-sm text-gray-600">{t("betNoPoints")}</p>
      <ul className="mt-3 flex flex-wrap gap-2">
        {choices.map((choice) => (
          <li key={choice.id} className="min-w-[44%] flex-1">
            <button
              type="button"
              disabled={picked !== undefined || locked}
              aria-pressed={picked === choice.id}
              onClick={() => {
                setPicked(choice.id);
                onBet(choice.id);
              }}
              className={`min-h-11 w-full rounded-full border-2 px-4 py-2 text-center font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                picked === choice.id
                  ? "border-teal-600 bg-teal-50 text-teal-900"
                  : "border-gray-300 bg-white text-gray-900 hover:border-teal-400"
              }`}
            >
              {text({ en: choice.en, fr: choice.fr }, target, home)}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function BetDemo({
  visual,
  params,
  caption,
  lang,
  question,
  chosen,
  target,
  home,
}: {
  visual: string;
  params?: Record<string, unknown>;
  caption?: string;
  lang: "fr" | "en";
  /** The bet this demo observes, when it is in the story. */
  question?: Question;
  /** The chip the learner picked, if they bet. */
  chosen?: string;
  target: string;
  home: string;
}) {
  const t = useTranslations("Story");
  const [done, setDone] = useState(false);
  const mine = question?.choices?.find((c) => c.id === chosen);
  const matched = !!question && chosen !== undefined && chosen === String(question.answer);
  const reaction = question?.reveal?.[matched ? "right" : "wrong"];
  return (
    <div>
      <ConceptVisual visual={visual} params={params} caption={caption} language={lang} onDone={() => setDone(true)} />
      {/* Always mounted, so the reveal is announced when it fills. */}
      <div role="status" aria-live="polite" className="mt-2">
        {done && mine ? (
          <div className="rounded-lg border border-teal-200 bg-teal-50 p-3">
            <p className="text-sm font-semibold text-teal-900">
              {t("betYours", { answer: text({ en: mine.en, fr: mine.fr }, target, home) })}
              {" · "}
              {matched ? t("betRight") : t("betWrong")}
            </p>
            {reaction ? <p className="mt-1 text-sm text-gray-800">{text(reaction, target, home)}</p> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
