/**
 * The story player (format Appendix A.4).
 *
 * One week reads as a continuous story. Steps are revealed one at a time so a
 * question stays on screen while she answers it and nothing below spoils the
 * answer — A.4 asks for a question right after each concept, and that only
 * works if the page does not show everything at once.
 *
 * Bilingual mode shows the language of instruction first and the home
 * language beneath it, which is how the printed booklet reads.
 *
 * Text is LANGUAGE-KEYED everywhere (contract C1): the `en` field of a
 * narrate/say/concept step is English and `fr` is French, exactly like a text
 * object, whatever `languages.target` says. So the player reads
 * `step[target]` first and `step[home]` beneath — for a French-target story
 * that is the `fr` field first.
 */

"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { starsFor, text } from "@/lib/story-course/answer";
import type {
  CastMember,
  Exercise,
  Minigame,
  Question,
  Step,
  StoryCourse,
  Video,
} from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { MinigameView } from "./minigame";
import { QuestionCard } from "./question-card";

interface FlatStep {
  step: Step;
  chapterId: string;
  chapterTitle: Record<string, string>;
  sceneId: string;
  place: string;
  /** First step of its chapter, so the player can print a chapter heading. */
  startsChapter: boolean;
}

/** A step the learner must deal with before the story moves on. */
const BLOCKING: ReadonlySet<string> = new Set(["ask", "game", "photo"]);

/**
 * Moods stand in for the character art the player does not draw yet. An emoji
 * reads the same in every language, where the raw mood id ("think") did not.
 */
const MOOD_EMOJI: Record<string, string> = {
  talk: "💬",
  happy: "😊",
  think: "🤔",
  sad: "😟",
  surprised: "😮",
  walk: "🚶",
};

/** A source figure is served in the lesson's languages only. */
function figureLanguage(target: string, home: string): "fr" | "en" {
  if (target === "fr" || target === "en") return target;
  return home === "fr" ? "fr" : "en";
}

/** A step's own text in one language: a line (narrate/say) or rows (concept). */
function stepText(step: Step, lang: string): string | string[] | undefined {
  const value = (step as unknown as Record<string, unknown>)[lang];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((row) => String(row));
  return undefined;
}

export interface StoryPlayerProps {
  course: StoryCourse;
  /**
   * `page` (default) is the standalone week: a sticky header and a Continue
   * bar fixed to the bottom of the screen. `embedded` sits inside another
   * page's card — the lesson's Story tab — so everything stays in the flow and
   * nothing covers the lesson's own controls or the mobile bottom navigation.
   */
  variant?: "page" | "embedded";
  /**
   * Fires once, when the learner reaches the last step and has settled it (a
   * question at the very end must be answered first). The lesson's Story tab
   * uses it to complete the lesson unit.
   */
  onComplete?: (outcome: { points: number; maxPoints: number }) => void;
  /**
   * False while the player is out of sight: the lesson keeps every tab
   * mounted, so a hidden Story tab is still on the page. A running mini-game
   * pauses its clock and stops listening to the keyboard until it is back.
   */
  active?: boolean;
}

export function StoryPlayer({
  course,
  variant = "page",
  onComplete,
  active = true,
}: StoryPlayerProps) {
  const t = useTranslations("Story");
  const target = course.languages?.target ?? "en";
  const home = course.languages?.home ?? "fr";
  const embedded = variant === "embedded";
  // Embedded, the lesson page already owns the h1.
  const TitleTag = embedded ? "h2" : "h1";
  const ChapterTag = embedded ? "h3" : "h2";

  const [bilingual, setBilingual] = useState(true);
  const [revealed, setRevealed] = useState(0);
  const [points, setPoints] = useState(0);
  const [settledSteps, setSettledSteps] = useState<Set<number>>(new Set());
  const endRef = useRef<HTMLDivElement | null>(null);
  // Mirrors settledSteps synchronously so a step can only ever score once,
  // even if a child reports twice before React re-renders.
  const settledRef = useRef<Set<number>>(new Set());

  const flat = useMemo<FlatStep[]>(() => {
    const out: FlatStep[] = [];
    for (const chapter of course.chapters ?? []) {
      let first = true;
      for (const scene of chapter.scenes ?? []) {
        for (const step of scene.steps ?? []) {
          out.push({
            step,
            chapterId: chapter.id,
            chapterTitle: chapter.title,
            sceneId: scene.id,
            place: scene.place,
            startsChapter: first,
          });
          first = false;
        }
      }
    }
    return out;
  }, [course.chapters]);

  const questions = useMemo(
    () => new Map((course.questions ?? []).map((q) => [q.id, q])),
    [course.questions],
  );
  const exercises = useMemo(
    () => new Map((course.exercises ?? []).map((e) => [e.id, e])),
    [course.exercises],
  );
  const games = useMemo(
    () => new Map((course.minigames ?? []).map((g) => [g.id, g])),
    [course.minigames],
  );
  const videos = useMemo(
    () => new Map((course.videos ?? []).map((v) => [v.id, v])),
    [course.videos],
  );
  const cast = useMemo(
    () => new Map((course.cast ?? []).map((c) => [c.id, c])),
    [course.cast],
  );

  const maxPoints = Number(course.checks?.max_points ?? 0);
  const unitLabel = text(course.rewards?.unit, target, home) || t("pointsUnit");

  const advance = useCallback(() => {
    setRevealed((index) => Math.min(index + 1, flat.length - 1));
    requestAnimationFrame(() =>
      // Embedded, the page carries on below the story, so scroll only as far
      // as needed to show the new step; standalone, scroll to the bottom.
      // (Optional call: jsdom and some old WebViews lack scrollIntoView.)
      endRef.current?.scrollIntoView?.({
        behavior: "smooth",
        block: embedded ? "nearest" : "start",
      }),
    );
  }, [flat.length, embedded]);

  const settle = useCallback((index: number, earned: number) => {
    if (settledRef.current.has(index)) return;
    settledRef.current.add(index);
    setPoints((total) => total + earned);
    setSettledSteps(new Set(settledRef.current));
  }, []);

  const current = flat[revealed];
  const currentIsBlocking = current ? BLOCKING.has(current.step.type) : false;
  const currentSettled = settledSteps.has(revealed);
  const lastIndex = flat.length - 1;
  const atEnd = revealed >= lastIndex;
  const canContinue = !atEnd && (!currentIsBlocking || currentSettled);
  // The end is reached once the last step is on screen and, if it asks
  // something of the learner, answered.
  const finished =
    flat.length > 0 &&
    atEnd &&
    (!BLOCKING.has(flat[lastIndex].step.type) || settledSteps.has(lastIndex));

  // Report completion exactly once. The callback is read through a ref so a
  // parent re-rendering with a new function cannot re-fire it.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);
  const completedRef = useRef(false);
  useEffect(() => {
    if (!finished || completedRef.current) return;
    completedRef.current = true;
    onCompleteRef.current?.({ points, maxPoints });
  }, [finished, points, maxPoints]);

  const stars = starsFor(maxPoints ? points / maxPoints : 0, course.rewards?.stars);
  const controls = finished ? (
    <div className="text-center" role="status">
      <p className="font-semibold text-gray-900">{t("finished")}</p>
      {stars > 0 ? (
        <p className="font-bold text-gray-900" aria-hidden="true">
          {"⭐".repeat(stars)}
        </p>
      ) : null}
      <p className="text-sm text-gray-600">
        {maxPoints
          ? t("scoreOf", { points, max: maxPoints, unit: unitLabel })
          : t("score", { points, unit: unitLabel })}
      </p>
    </div>
  ) : (
    <button
      type="button"
      onClick={advance}
      disabled={!canContinue}
      className="min-h-11 w-full rounded-lg bg-teal-600 font-semibold text-white hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-gray-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
    >
      {currentIsBlocking && !currentSettled ? t("answerToContinue") : t("continueLabel")}
    </button>
  );

  return (
    <div className={embedded ? "mx-auto max-w-2xl" : "mx-auto max-w-2xl px-4 pb-24"}>
      {/* Header: title and running score. */}
      <header
        className={
          embedded
            ? "mb-4 border-b border-teal-100 pb-3"
            : "sticky top-0 z-10 -mx-4 mb-4 border-b border-teal-100 bg-white/95 px-4 py-3 backdrop-blur"
        }
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {/* Standalone weeks say where they sit; the lesson page already does. */}
            {!embedded ? (
              <p className="truncate text-xs uppercase tracking-wide text-gray-500">
                {[course.course, course.unit, t("week", { week: course.week })]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            ) : null}
            <TitleTag
              className={`font-bold text-gray-900 ${embedded ? "text-base" : "truncate text-lg"}`}
            >
              {text(course.title, target, home)}
            </TitleTag>
          </div>
          <div className="shrink-0 text-right">
            <p className="font-bold text-teal-700" aria-live="polite">
              {points}
              {maxPoints ? <span className="text-gray-400">/{maxPoints}</span> : null}
            </p>
            <p className="text-xs text-gray-500">{unitLabel}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setBilingual((on) => !on)}
          aria-pressed={bilingual}
          title={t("bilingualToggle")}
          className="mt-2 min-h-11 rounded-lg border border-gray-300 px-3 text-sm text-gray-700 hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <span className="sr-only">{t("bilingualToggle")}: </span>
          {bilingual
            ? `${target.toUpperCase()} + ${home.toUpperCase()}`
            : target.toUpperCase()}
        </button>
      </header>

      <ol className="space-y-1">
        {flat.slice(0, revealed + 1).map((item, index) => (
          <li key={`${item.sceneId}-${index}`}>
            {item.startsChapter ? (
              <ChapterTag className="mt-6 mb-2 border-l-4 border-amber-400 pl-3 text-base font-bold text-gray-900">
                {text(item.chapterTitle, target, home)}
              </ChapterTag>
            ) : null}
            <StepView
              step={item.step}
              place={item.place}
              target={target}
              home={home}
              bilingual={bilingual}
              cast={cast}
              question={item.step.ref ? questions.get(item.step.ref) : undefined}
              exercise={item.step.ref ? exercises.get(item.step.ref) : undefined}
              game={item.step.ref ? games.get(item.step.ref) : undefined}
              video={item.step.ref ? videos.get(item.step.ref) : undefined}
              rewards={course.rewards}
              active={active}
              settled={settledSteps.has(index)}
              onSettled={(earned) => settle(index, earned)}
            />
          </li>
        ))}
      </ol>

      {embedded ? (
        <>
          {/* Continue / finish, in the flow right under the newest step. */}
          <div className="mt-6">{controls}</div>
          <div ref={endRef} />
        </>
      ) : (
        <>
          <div ref={endRef} />
          {/* Continue / finish */}
          <div className="fixed inset-x-0 bottom-0 border-t border-gray-200 bg-white/95 p-3 backdrop-blur">
            <div className="mx-auto max-w-2xl">{controls}</div>
          </div>
        </>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

interface StepViewProps {
  step: Step;
  place: string;
  target: string;
  home: string;
  bilingual: boolean;
  cast: Map<string, CastMember>;
  question?: Question;
  exercise?: Exercise;
  game?: Minigame;
  video?: Video;
  rewards?: StoryCourse["rewards"];
  active: boolean;
  settled: boolean;
  onSettled: (earned: number) => void;
}

function StepView({
  step,
  target,
  home,
  bilingual,
  cast,
  question,
  exercise,
  game,
  video,
  rewards,
  active,
  settled,
  onSettled,
}: StepViewProps) {
  const t = useTranslations("Story");
  const line = (value: string | string[] | undefined): string =>
    Array.isArray(value) ? value.join("\n") : (value ?? "");

  // Language-keyed (C1): the target language's field first, the home
  // language's beneath. Falls back to the home text when a step only has that.
  const targetLine = line(stepText(step, target));
  const homeLine = line(stepText(step, home));
  const primaryLine = targetLine || homeLine;
  const primaryLang = targetLine ? target : home;
  const showHomeLine = bilingual && !!targetLine && !!homeLine && homeLine !== targetLine;

  switch (step.type) {
    case "narrate":
      return (
        <div className="my-3 border-l-2 border-gray-200 pl-3">
          <p className="text-gray-700" lang={primaryLang}>
            {primaryLine}
          </p>
          {showHomeLine ? (
            <p className="mt-1 text-sm italic text-gray-500" lang={home}>
              {homeLine}
            </p>
          ) : null}
        </div>
      );

    case "say": {
      const speaker = step.who ? cast.get(step.who) : undefined;
      const isTutor = speaker?.kind === "ai_tutor";
      const mood = step.mood ? MOOD_EMOJI[step.mood] : undefined;
      return (
        <div className="my-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">
            {speaker?.name ?? step.who}
            {isTutor ? ` (${t("aiLabel")})` : ""}
            {mood ? (
              <span className="ml-2 font-normal" aria-hidden="true">
                {mood}
              </span>
            ) : null}
          </p>
          <div
            className={`mt-1 rounded-2xl px-4 py-2 ${
              isTutor ? "bg-amber-100" : "bg-teal-50"
            }`}
          >
            <p className="text-gray-900" lang={primaryLang}>
              {primaryLine}
            </p>
            {showHomeLine ? (
              <p className="mt-1 text-sm italic text-gray-600" lang={home}>
                {homeLine}
              </p>
            ) : null}
          </div>
        </div>
      );
    }

    case "show":
      return (
        <ConceptVisual
          visual={step.visual ?? "unknown"}
          params={step.params}
          caption={step.caption ? text(step.caption, target, home) : undefined}
          language={figureLanguage(target, home)}
        />
      );

    case "concept": {
      // Rows are language-keyed too (C1): `fr` holds the French rows.
      const rowsIn = (lang: string): string[] => {
        const value = stepText(step, lang);
        return Array.isArray(value) ? value : [];
      };
      const targetRows = rowsIn(target);
      const homeRows = rowsIn(home);
      const rows = targetRows.length ? targetRows : homeRows;
      return (
        <section className="my-4 rounded-xl border border-teal-200 bg-white p-4">
          {step.title ? (
            <h3 className="font-bold text-gray-900">{text(step.title, target, home)}</h3>
          ) : null}
          <ul className="mt-2 space-y-2">
            {rows.map((row, index) => (
              <li key={index} className="text-sm">
                <p className="text-gray-800" lang={targetRows.length ? target : home}>
                  {row}
                </p>
                {bilingual && targetRows.length > 0 && homeRows[index] && homeRows[index] !== row ? (
                  <p className="italic text-gray-500" lang={home}>
                    {homeRows[index]}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      );
    }

    case "ask":
      if (!question) return <MissingRef kind="question" refId={step.ref} />;
      return (
        <QuestionCard
          question={question}
          target={target}
          home={home}
          bilingual={bilingual}
          rewards={rewards}
          onAnswered={({ points }) => onSettled(points)}
        />
      );

    case "game":
      if (!game) return <MissingRef kind="mini-game" refId={step.ref} />;
      return (
        <MinigameView
          game={game}
          target={target}
          home={home}
          bilingual={bilingual}
          active={active}
          onFinished={({ points }) => onSettled(points)}
        />
      );

    case "photo":
      if (!exercise) return <MissingRef kind="exercise" refId={step.ref} />;
      return (
        <PaperExercise
          exercise={exercise}
          target={target}
          home={home}
          bilingual={bilingual}
          settled={settled}
          onDone={() => onSettled(0)}
        />
      );

    case "video":
      if (!video) return <MissingRef kind="video" refId={step.ref} />;
      return (
        <a
          href={video.url}
          target="_blank"
          rel="noopener noreferrer"
          className="my-3 flex min-h-11 items-center gap-3 rounded-xl border border-gray-200 bg-white p-3 hover:border-teal-400"
        >
          <span aria-hidden="true">{"▶"}</span>
          <span>
            <span className="block font-semibold text-gray-900">{video.title}</span>
            <span className="block text-xs text-gray-500">
              {`${video.provider} · ${video.lang.toUpperCase()}`}
            </span>
          </span>
        </a>
      );

    default:
      return null;
  }
}

/**
 * A paper-and-pen exercise (A.6).
 *
 * Photo checking needs a camera and the AI relay, which this slice does not
 * wire up. Until then the exercise is shown to do on paper with its marks and
 * its worked solution available afterwards, which is the part that works
 * offline anyway.
 */
function PaperExercise({
  exercise,
  target,
  home,
  bilingual,
  settled,
  onDone,
}: {
  exercise: Exercise;
  target: string;
  home: string;
  bilingual: boolean;
  settled: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("Story");
  const [showWorking, setShowWorking] = useState(false);
  const working = exercise.working ?? {};

  return (
    <section className="my-5 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {[
          t("onPaper"),
          exercise.id,
          t("part", { part: exercise.part }),
          exercise.marks ? `[${exercise.marks}]` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <p className="mt-2 font-medium text-gray-900">{text(exercise.prompt, target, home)}</p>
      {bilingual ? (
        <p className="mt-1 text-sm italic text-gray-500" lang={home}>
          {text(exercise.prompt, home, target)}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        {!settled ? (
          <button
            type="button"
            onClick={onDone}
            className="min-h-11 rounded-lg bg-gray-800 px-4 font-semibold text-white hover:bg-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-700"
          >
            {t("doneOnPaper")}
          </button>
        ) : null}
        {settled ? (
          <button
            type="button"
            onClick={() => setShowWorking((on) => !on)}
            className="min-h-11 rounded-lg border border-gray-400 px-4 font-semibold text-gray-800"
          >
            {showWorking ? t("hideWorking") : t("showWorking")}
          </button>
        ) : null}
      </div>

      {settled && showWorking ? (
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
    </section>
  );
}

function MissingRef({ kind, refId }: { kind: string; refId?: string }) {
  const t = useTranslations("Story");
  return (
    <p className="my-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      {t("missingRef", { kind, ref: refId ?? "?" })}
    </p>
  );
}
