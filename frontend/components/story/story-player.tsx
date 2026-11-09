/**
 * The story player (format Appendix A.4): a cartoon stage (#2673).
 *
 * A painted place, the cast standing on the ground, and one step at a time:
 * a speech bubble over whoever speaks, a caption bar for the narrator, a
 * chalkboard for a concept, a card on the stage for a question or a game.
 * Steps are revealed one at a time so a question stays in front of the
 * learner while they answer it and nothing after it spoils the answer — A.4
 * asks for a question right after each concept.
 *
 * Bilingual mode shows the language of instruction first and the home
 * language beneath it, which is how the printed booklet reads. It starts on
 * for a standalone week and off inside a lesson, where the learner has
 * already chosen her language; the lesson's choice is remembered per browser.
 *
 * Text is LANGUAGE-KEYED everywhere (contract C1): the `en` field of a
 * narrate/say/concept step is English and `fr` is French, exactly like a text
 * object, whatever `languages.target` says. So the player reads
 * `step[target]` first and `step[home]` beneath — for a French-target story
 * that is the `fr` field first.
 *
 * The stage itself lives in `./stage`: the cast and their placeholder
 * figures, the backdrops, the panels, sound and read-aloud.
 */

"use client";

import { Volume2, VolumeX } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import { starsFor, text } from "@/lib/story-course/answer";
import {
  NAME_FALLBACKS,
  asksFriendName,
  castFriendName,
  personalizeStory,
  type StoryLanguage,
} from "@/lib/story-course/personalize";
import { chapterLocalId } from "@/lib/story-course/progress";
import type { Step, StoryCourse } from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { MinigameView } from "./minigame";
import { QuestionCard } from "./question-card";
import { Backdrop } from "./stage/backdrop";
import { artFor, buildActors, heroVariants, poseFor, safeArtUrl, slotsFor, type Pose } from "./stage/cast";
import { Confetti, StarRow } from "./stage/confetti";
import { CaptionBar, Chalkboard, SpeechBubble, StageCard, VisualPanel, type SkipHandle } from "./stage/panels";
import { PaperExercise } from "./stage/paper-exercise";
import { placeLook, placeTheme, placeTitle } from "./stage/places";
import {
  readChoices,
  readSoundOn,
  useReducedMotion,
  writeChoices,
  writeSoundOn,
  type StoryChoices,
} from "./stage/prefs";
import { planSteps, presenterOf, reactorOf, type PlannedStep } from "./stage/scene-plan";
import { playSfx, unlockAudio, type Sfx } from "./stage/sound";
import { speak, stopSpeaking, type SpeechVoice } from "./stage/speech";
import { StageCharacter, type Gesture } from "./stage/stage-character";
import styles from "./stage/stage.module.css";
import { PlaceRibbon, PlayIcon, StartCard, TitleCard } from "./stage/title-card";
import type { TypedHandle } from "./stage/typed-text";

/** A step the learner must deal with before the story moves on. */
const BLOCKING: ReadonlySet<string> = new Set(["ask", "game", "photo"]);

/** Steps whose panel a tap on the stage may carry past. */
const TAP_THROUGH: ReadonlySet<string> = new Set(["say", "narrate", "concept", "show", "video"]);

/** Steps that put a panel on the stage with a pop. */
const POP_STEPS: ReadonlySet<string> = new Set(["concept", "show", "ask", "game", "photo", "video"]);

const NARRATOR: SpeechVoice = { pitch: 1, rate: 0.95 };

/** Where the embedded player (the module story panel) keeps the bilingual toggle, per browser. */
export const EMBEDDED_BILINGUAL_KEY = "sira.story.bilingual";

/**
 * The embedded player's starting bilingual mode: whatever this viewer chose
 * last, else off. Storage can be missing or throw (private mode, blocked site
 * data), so any failure just means "off".
 */
function readEmbeddedBilingual(): boolean {
  try {
    return window.localStorage.getItem(EMBEDDED_BILINGUAL_KEY) === "on";
  } catch {
    return false;
  }
}

function writeEmbeddedBilingual(on: boolean): void {
  try {
    window.localStorage.setItem(EMBEDDED_BILINGUAL_KEY, on ? "on" : "off");
  } catch {
    // Not remembered; the toggle still works for this visit.
  }
}

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

function lineOf(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value.join("\n") : (value ?? "");
}

function rowsOf(step: Step, lang: string): string[] {
  const value = stepText(step, lang);
  return Array.isArray(value) ? value : [];
}

/** How long a line takes to say, in seconds: read aloud, or typed out. */
function lineSeconds(line: string, sound: boolean): number {
  return Math.min(16, Math.max(1, line.length / (sound ? 14 : 38)));
}

/** When each chalkboard row comes up: after the title and the rows before it are read. */
function rowDelays(rows: string[], title: string | undefined, sound: boolean): number[] {
  const pace = sound ? 18 : 32;
  let at = 0.35 + (title ? Math.min(1.5, title.length / pace) : 0);
  return rows.map((row) => {
    const delay = at;
    at += Math.min(3.5, Math.max(0.7, row.length / pace));
    return delay;
  });
}

export interface StoryPlayerProps {
  course: StoryCourse;
  /**
   * `page` (default) is the standalone week: a sticky header and a Next bar
   * fixed to the bottom of the screen. `embedded` sits inside another page's
   * card — the module story panel — so everything stays in the flow and
   * nothing covers the page's own controls or the mobile bottom navigation.
   */
  variant?: "page" | "embedded";
  /**
   * Fires once, when the learner reaches the last step and has settled it (a
   * question at the very end must be answered first). The module story panel
   * uses it to finish a chapter, which can complete that chapter's lesson unit.
   */
  onComplete?: (outcome: { points: number; maxPoints: number }) => void;
  /**
   * False while the player is out of sight but still mounted (a host that
   * keeps hidden panes on the page, as tabs do). A running mini-game pauses
   * its clock and stops listening to the keyboard, and read-aloud stops.
   */
  active?: boolean;
  /**
   * Play only this chapter (a module story is played one chapter at a time,
   * so the page holds one chapter's steps, not the whole module's). The
   * chapter's title becomes the player's heading.
   */
  chapterId?: string;
  /**
   * The points this player can award, instead of the document's
   * `checks.max_points` (which, for a module story, covers every chapter).
   */
  maxPoints?: number;
  /**
   * No "Story complete" block with stars and score at the end: the parent
   * shows its own. `onComplete` still fires once, and the stage still cheers.
   */
  hideFinishSummary?: boolean;
}

export function StoryPlayer({
  course,
  variant = "page",
  onComplete,
  active = true,
  chapterId,
  maxPoints: maxPointsOverride,
  hideFinishSummary = false,
}: StoryPlayerProps) {
  const t = useTranslations("Story");
  const target = course.languages?.target ?? "en";
  const home = course.languages?.home ?? "fr";
  const embedded = variant === "embedded";
  const reducedMotion = useReducedMotion();
  // Embedded, the lesson page already owns the h1.
  const TitleTag = embedded ? "h2" : "h1";
  const ChapterTag = embedded ? "h3" : "h2";
  const storyLang: StoryLanguage = target === "fr" || target === "en" ? target : home === "fr" ? "fr" : "en";

  // Standalone weeks open bilingual, like the booklet. In a lesson the
  // learner already picked her language, so the second line starts off.
  const [bilingual, setBilingual] = useState(() => (embedded ? readEmbeddedBilingual() : true));
  const toggleBilingual = () => {
    const next = !bilingual;
    setBilingual(next);
    if (embedded) writeEmbeddedBilingual(next);
  };

  // One switch for read-aloud and sound effects, remembered per browser.
  const [soundOn, setSoundOn] = useState(readSoundOn);
  const soundRef = useRef(soundOn);
  useEffect(() => {
    soundRef.current = soundOn;
  }, [soundOn]);
  const sfx = useCallback((name: Sfx) => {
    if (soundRef.current) playSfx(name);
  }, []);
  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    writeSoundOn(next);
    if (next) unlockAudio();
    else stopSpeaking();
  };

  // The learner's choices at the start of a course's story (#2672): the
  // friend's name and which hero they are. Asked once per course and browser.
  const courseKey = course.course || course.id;
  const variants = useMemo(() => heroVariants(course), [course]);
  const asksFriend = useMemo(() => asksFriendName(course), [course]);
  const [choices, setChoices] = useState<StoryChoices | null>(() =>
    asksFriend || variants.length ? readChoices(courseKey) : {},
  );
  const introOpen = choices === null;
  // The look being tried on in the start card, worn on stage right away.
  const [preview, setPreview] = useState<string | undefined>(undefined);
  const wanted = introOpen ? preview : choices?.variant;
  const variantId = variants.length ? (wanted && variants.includes(wanted) ? wanted : variants[0]) : undefined;

  // `{friend}` is filled here (the host fills `{child}`), on a copy.
  const story = useMemo(
    () => personalizeStory(course, { friend: choices?.friend, language: storyLang, keep: ["child"] }),
    [course, choices?.friend, storyLang],
  );
  const actors = useMemo(() => buildActors(story, variantId), [story, variantId]);

  // One chapter, or the whole week.
  const chapters = useMemo(
    () =>
      chapterId === undefined
        ? (story.chapters ?? [])
        : (story.chapters ?? []).filter((chapter) => chapter.id === chapterId),
    [story.chapters, chapterId],
  );
  const singleChapter = chapterId !== undefined ? chapters[0] : undefined;
  const flat = useMemo<PlannedStep[]>(
    () => planSteps(chapters, story.chapters ?? [], actors),
    [chapters, story.chapters, actors],
  );

  const questions = useMemo(() => new Map((story.questions ?? []).map((q) => [q.id, q])), [story.questions]);
  const exercises = useMemo(() => new Map((story.exercises ?? []).map((e) => [e.id, e])), [story.exercises]);
  const games = useMemo(() => new Map((story.minigames ?? []).map((g) => [g.id, g])), [story.minigames]);
  const videos = useMemo(() => new Map((story.videos ?? []).map((v) => [v.id, v])), [story.videos]);

  const maxPoints =
    maxPointsOverride !== undefined
      ? Math.max(0, Number(maxPointsOverride) || 0)
      : Number(story.checks?.max_points ?? 0);
  const unitLabel = text(story.rewards?.unit, target, home) || t("pointsUnit");

  const [index, setIndex] = useState(0);
  const [points, setPoints] = useState(0);
  const [settledSteps, setSettledSteps] = useState<Set<number>>(new Set());
  // Mirrors settledSteps synchronously so a step can only ever score once,
  // even if a child reports twice before React re-renders.
  const settledRef = useRef<Set<number>>(new Set());
  // The hero's reaction to the latest answer on the current step.
  const [reaction, setReaction] = useState<{ index: number; correct: boolean; n: number } | null>(null);
  const [bursts, setBursts] = useState(0);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const controlsRef = useRef<HTMLDivElement | null>(null);
  const typedRef = useRef<TypedHandle | null>(null);
  const boardRef = useRef<SkipHandle | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  const advance = useCallback(() => {
    setIndex((current) => Math.min(current + 1, flat.length - 1));
    requestAnimationFrame(() =>
      // Keep the stage and the Next button in view on a phone. (Optional
      // call: jsdom and some old WebViews lack scrollIntoView.)
      (embedded ? controlsRef : frameRef).current?.scrollIntoView?.({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "nearest",
      }),
    );
  }, [flat.length, embedded, reducedMotion]);

  const settle = useCallback((stepIndex: number, earned: number) => {
    if (settledRef.current.has(stepIndex)) return;
    settledRef.current.add(stepIndex);
    setPoints((total) => total + earned);
    setSettledSteps(new Set(settledRef.current));
  }, []);

  const current = flat[index];
  const currentIsBlocking = current ? BLOCKING.has(current.step.type) : false;
  const currentSettled = settledSteps.has(index);
  const lastIndex = flat.length - 1;
  const atEnd = index >= lastIndex;
  const canContinue = !introOpen && !atEnd && (!currentIsBlocking || currentSettled);
  // The end is reached once the last step is on screen and, if it asks
  // something of the learner, answered.
  const finished =
    flat.length > 0 &&
    atEnd &&
    (!BLOCKING.has(flat[lastIndex].step.type) || settledSteps.has(lastIndex));
  // A chapter that was actually played through gets a cheer; one that is
  // complete the moment it opens (a one-line checkpoint) does not.
  const celebrating = finished && !introOpen && (index > 0 || settledSteps.size > 0);

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

  const cheeredRef = useRef(false);
  useEffect(() => {
    if (!celebrating || cheeredRef.current) return;
    cheeredRef.current = true;
    sfx("fanfare");
  }, [celebrating, sfx]);

  // A whoosh for a new place, a pop for a card.
  const lastPlaceRun = useRef<number | null>(null);
  useEffect(() => {
    if (!current || introOpen) return;
    if (lastPlaceRun.current !== null && lastPlaceRun.current !== current.placeRun) sfx("whoosh");
    else if (POP_STEPS.has(current.step.type)) sfx("pop");
    lastPlaceRun.current = current.placeRun;
  }, [current, introOpen, sfx]);

  // Who is on stage now, and who does what.
  const cast = current?.cast ?? [];
  const slots = slotsFor(cast.length);
  const reactor = reactorOf(cast, actors);
  const presenter = presenterOf(cast, actors);
  const step = current?.step;
  const speakerId = step?.type === "say" ? step.who : step?.type === "concept" ? presenter : undefined;

  // Read-aloud: the step's target-language text, in its speaker's voice.
  const speech = useMemo(() => {
    if (!step) return null;
    const targetLine = lineOf(stepText(step, target));
    const homeLine = lineOf(stepText(step, home));
    const lang = targetLine ? target : home;
    const voiceOf = (id: string | undefined) => (id ? actors.get(id)?.voice : undefined) ?? NARRATOR;
    switch (step.type) {
      case "say":
        return { lines: [targetLine || homeLine], lang, voice: voiceOf(step.who) };
      case "narrate":
        return { lines: [targetLine || homeLine], lang, voice: NARRATOR };
      case "concept": {
        const rows = rowsOf(step, target).length ? rowsOf(step, target) : rowsOf(step, home);
        const title = step.title ? text(step.title, target, home) : "";
        return { lines: [title, ...rows], lang, voice: voiceOf(presenter) };
      }
      case "show":
        return step.caption ? { lines: [text(step.caption, target, home)], lang: target, voice: NARRATOR } : null;
      case "ask": {
        const question = step.ref ? questions.get(step.ref) : undefined;
        return question ? { lines: [text(question.prompt, target, home)], lang: target, voice: NARRATOR } : null;
      }
      case "game": {
        const game = step.ref ? games.get(step.ref) : undefined;
        return game
          ? { lines: [text(game.title, target, home), text(game.instruction, target, home)], lang: target, voice: NARRATOR }
          : null;
      }
      default:
        return null;
    }
  }, [step, target, home, actors, presenter, questions, games]);

  useEffect(() => {
    if (!soundOn || !active || introOpen || !speech) return;
    speak(speech.lines, speech.lang, speech.voice);
    return () => stopSpeaking();
  }, [speech, soundOn, active, introOpen]);

  // Space and → move on, like the Next button, when the story has the focus
  // (or nothing does) and the key is not meant for a field or a button.
  const tryAdvanceRef = useRef<() => void>(() => {});
  useEffect(() => {
    tryAdvanceRef.current = () => {
      if (canContinue) advance();
    };
  }, [canContinue, advance]);
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
      if (event.key !== " " && event.key !== "ArrowRight") return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
      // A focused button already answers Space itself.
      if (event.key === " " && target?.closest("button, a, summary, [role=button]")) return;
      if (target && target !== document.body && !rootRef.current?.contains(target)) return;
      event.preventDefault();
      tryAdvanceRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  // A tap on the stage finishes the line being typed, then moves on. Never
  // while a question, a game or a paper exercise is waiting.
  const onStageTap = (event: MouseEvent) => {
    if (introOpen || finished || !current || !TAP_THROUGH.has(current.step.type)) return;
    if (event.target instanceof Element && event.target.closest("button, a, input, select, textarea, label")) return;
    if (typedRef.current?.skip() || boardRef.current?.skip()) return;
    if (canContinue) advance();
  };

  const startStory = (picked: StoryChoices) => {
    unlockAudio();
    const next: StoryChoices = {
      friend: picked.friend,
      variant: picked.variant,
    };
    writeChoices(courseKey, next);
    setChoices(next);
    sfx("whoosh");
  };

  const onAttempt = (stepIndex: number) => (outcome: { correct: boolean }) => {
    setReaction((previous) => ({ index: stepIndex, correct: outcome.correct, n: (previous?.n ?? 0) + 1 }));
    // The hint or the explanation lands at the bottom of the card: bring it
    // into view inside a card that scrolls on the stage.
    requestAnimationFrame(() => {
      const card = cardRef.current;
      card?.scrollTo?.({ top: card.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
    });
    if (outcome.correct) {
      sfx("correct");
      setBursts((n) => n + 1);
    } else {
      sfx("oops");
    }
  };

  const stars = starsFor(maxPoints ? points / maxPoints : 0, story.rewards?.stars);

  /* ---- The stage ------------------------------------------------------- */

  const firstStep = flat[0];
  const placeId = (current ?? firstStep)?.place ?? "";
  const theme = placeTheme(placeId, placeLook(story, placeId));
  const backdropUrl = safeArtUrl(story.art?.places?.[placeId]);
  const stageCast = introOpen ? (firstStep?.cast ?? []) : cast;
  const stageSlots = introOpen ? slotsFor(stageCast.length) : slots;
  const showTitle = introOpen || !!current?.startsChapter;
  const titleCard = (() => {
    const chapterItem = current ?? firstStep;
    if (!showTitle || !chapterItem) return null;
    const wholeStoryStart = introOpen || (!singleChapter && index === 0);
    const titleObject = wholeStoryStart && !singleChapter ? story.title : chapterItem.chapterTitle;
    const primary = text(titleObject, target, home);
    const secondary = text(titleObject, home, target);
    const eyebrow = wholeStoryStart && !singleChapter
      ? [story.course, story.unit].filter(Boolean).join(" · ")
      : t("chapterNumber", { number: chapterItem.chapterNumber });
    const footer =
      wholeStoryStart && !singleChapter && chapters.length > 1 && !introOpen
        ? `${t("chapterNumber", { number: chapterItem.chapterNumber })} · ${text(chapterItem.chapterTitle, target, home)}`
        : undefined;
    return (
      <TitleCard
        eyebrow={eyebrow || undefined}
        title={primary}
        titleLang={target}
        subtitle={bilingual && secondary && secondary !== primary ? secondary : undefined}
        subtitleLang={home}
        footer={footer}
      />
    );
  })();
  // "Where are we": on a scene's first line, when no card covers that corner.
  const ribbonTitle =
    !showTitle && current?.startsScene && (step?.type === "say" || step?.type === "narrate")
      ? placeTitle(story, current.place)
      : undefined;

  const poseOf = (id: string): Pose => {
    if (celebrating) return "happy";
    if (introOpen || !step) return "idle";
    if (reaction && reaction.index === index && id === reactor) return reaction.correct ? "happy" : "think";
    if (step.type === "say" && step.who === id) return poseFor(step.mood, true);
    if (step.type === "concept" && id === presenter) return "talk";
    if ((step.type === "ask" || step.type === "game" || step.type === "photo") && id === reactor) return "think";
    return "idle";
  };

  const speakingLine = step && speakerId ? lineOf(stepText(step, target)) || lineOf(stepText(step, home)) : "";
  const speakBeats = Math.max(2, Math.min(40, Math.round(lineSeconds(speakingLine, soundOn) / 0.42)));

  const characters = stageCast.map((id, slot) => {
    const actor = actors.get(id);
    if (!actor) return null;
    const pose = poseOf(id);
    const speaking = !introOpen && !celebrating && id === speakerId;
    const reacting = reaction && reaction.index === index && id === reactor && !celebrating;
    const gesture: Gesture = celebrating
      ? "jump"
      : reacting
        ? reaction.correct
          ? "jump"
          : "shake"
        : speaking
          ? "speak"
          : null;
    return (
      <StageCharacter
        key={id}
        actor={actor}
        x={stageSlots[slot]}
        pose={pose}
        artUrl={artFor(story.art, actor.artKey, pose)}
        gesture={gesture}
        // A new key restarts the gesture's animation; standing still keeps one.
        gestureKey={gesture ? `${gesture}-${index}-${reacting ? reaction.n : 0}` : "still"}
        beats={speaking ? speakBeats : 0}
        enterDelay={0.25 + slot * 0.3}
        speaking={speaking && step?.type === "say"}
      />
    );
  });

  /* ---- The step's panel ------------------------------------------------ */

  const panel = (() => {
    if (!current || !step) return null;
    const targetLine = lineOf(stepText(step, target));
    const homeLine = lineOf(stepText(step, home));
    const primary = targetLine || homeLine;
    const primaryLang = targetLine ? target : home;
    const secondary = bilingual && !!targetLine && !!homeLine && homeLine !== targetLine ? homeLine : undefined;
    const animate = !reducedMotion;
    switch (step.type) {
      case "narrate":
        return (
          <CaptionBar
            key={index}
            primary={primary}
            primaryLang={primaryLang}
            secondary={secondary}
            secondaryLang={home}
            animate={animate}
            typedRef={typedRef}
          />
        );
      case "say": {
        const actor = step.who ? actors.get(step.who) : undefined;
        const slot = step.who ? cast.indexOf(step.who) : -1;
        return (
          <SpeechBubble
            key={index}
            name={actor?.name ?? step.who ?? ""}
            aiLabel={actor?.isTutor ? t("aiLabel") : undefined}
            actor={actor}
            x={slot >= 0 ? slots[slot] : undefined}
            primary={primary}
            primaryLang={primaryLang}
            secondary={secondary}
            secondaryLang={home}
            animate={animate}
            typedRef={typedRef}
          />
        );
      }
      case "concept": {
        const targetRows = rowsOf(step, target);
        const homeRows = rowsOf(step, home);
        const rows = targetRows.length ? targetRows : homeRows;
        const title = step.title ? text(step.title, target, home) : undefined;
        return (
          <Chalkboard
            key={index}
            ref={boardRef}
            title={title}
            headingLevel={embedded ? 4 : 3}
            rows={rows}
            rowsLang={targetRows.length ? target : home}
            homeRows={bilingual && targetRows.length ? homeRows : []}
            homeLang={home}
            rowDelays={reducedMotion ? rows.map(() => 0) : rowDelays(rows, title, soundOn)}
          />
        );
      }
      case "show":
        return (
          <VisualPanel key={index}>
            <ConceptVisual
              visual={step.visual ?? "unknown"}
              params={step.params}
              caption={step.caption ? text(step.caption, target, home) : undefined}
              language={figureLanguage(target, home)}
            />
          </VisualPanel>
        );
      case "ask": {
        const question = step.ref ? questions.get(step.ref) : undefined;
        if (!question) return <MissingRef key={index} kind="question" refId={step.ref} />;
        return (
          <StageCard key={index} ref={cardRef} kind="ask" banner={t("questionBanner")} paper>
            <QuestionCard
              question={question}
              target={target}
              home={home}
              bilingual={bilingual}
              rewards={story.rewards}
              className="pt-2"
              onAnswered={({ points: earned }) => settle(index, earned)}
              onAttempt={onAttempt(index)}
            />
          </StageCard>
        );
      }
      case "game": {
        const game = step.ref ? games.get(step.ref) : undefined;
        if (!game) return <MissingRef key={index} kind="mini-game" refId={step.ref} />;
        return (
          <StageCard key={index} kind="game" banner={t("gameBanner")} bannerColor="#c2410c">
            <MinigameView
              game={game}
              target={target}
              home={home}
              bilingual={bilingual}
              active={active && !introOpen}
              className="pt-2"
              onTap={(correct) => sfx(correct ? "coin" : "oops")}
              onFinished={({ points: earned }) => {
                settle(index, earned);
                if (earned > 0) {
                  sfx("correct");
                  setBursts((n) => n + 1);
                }
              }}
            />
          </StageCard>
        );
      }
      case "photo": {
        const exercise = step.ref ? exercises.get(step.ref) : undefined;
        if (!exercise) return <MissingRef key={index} kind="exercise" refId={step.ref} />;
        return (
          <StageCard key={index} kind="photo">
            <PaperExercise
              exercise={exercise}
              label={story.module_story ? chapterLocalId(exercise.id) : exercise.id}
              target={target}
              home={home}
              bilingual={bilingual}
              settled={currentSettled}
              onMarked={(earned) => {
                settle(index, earned);
                if (earned > 0) sfx("coin");
              }}
            />
          </StageCard>
        );
      }
      case "video": {
        const video = step.ref ? videos.get(step.ref) : undefined;
        if (!video) return <MissingRef key={index} kind="video" refId={step.ref} />;
        return (
          <StageCard key={index} kind="video" banner={t("videoBanner")} bannerColor="#7c3aed">
            <a
              href={video.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 flex min-h-11 items-center gap-3 rounded-xl border-2 border-gray-200 bg-white p-3 hover:border-[#1d6fb8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1d6fb8]"
            >
              <span
                aria-hidden="true"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#1d2b4f] text-[#ffd23f]"
              >
                {"▶"}
              </span>
              <span>
                <span className="block font-semibold text-gray-900">{video.title}</span>
                <span className="block text-xs text-gray-600">
                  {`${video.provider} · ${video.lang.toUpperCase()}`}
                </span>
              </span>
            </a>
          </StageCard>
        );
      }
      default:
        return null;
    }
  })();

  /* ---- Start card, controls, summary ------------------------------------ */

  const heroActorId = [...actors.values()].find((actor) => actor.isHero)?.id;
  const startCard = introOpen ? (
    <StartCard
      askFriend={asksFriend}
      defaultFriend={castFriendName(course) ?? NAME_FALLBACKS.friend[storyLang]}
      variants={variants.flatMap((id) => {
        const actor = heroActorId ? buildActors(story, id).get(heroActorId) : undefined;
        return actor ? [{ id, actor, artUrl: artFor(story.art, `hero:${id}`, "idle") }] : [];
      })}
      initialVariant={variantId}
      onPreview={setPreview}
      onStart={startStory}
    />
  ) : null;

  const finishSummary =
    finished && !hideFinishSummary ? (
      <div
        role="status"
        className={`${styles.rise} mt-4 rounded-2xl border-[3px] border-[#ffd23f] px-4 py-4 text-center text-white shadow-[0_6px_0_rgba(29,43,79,0.25)]`}
        style={{ background: "radial-gradient(circle at 20% 10%, #2c3f73, #1d2b4f 70%)" }}
      >
        <p className={`${styles.titleText} text-2xl font-black`}>{t("finished")}</p>
        {stars > 0 ? (
          <p className="mt-2">
            <StarRow stars={stars} max={3} />
            <span className="sr-only">{t("starsLabel", { stars, max: 3 })}</span>
          </p>
        ) : null}
        <p className="mt-1 text-sm font-semibold text-sky-100">
          {maxPoints
            ? t("scoreOf", { points, max: maxPoints, unit: unitLabel })
            : t("score", { points, unit: unitLabel })}
        </p>
      </div>
    ) : null;

  const nextButton =
    finished || introOpen ? null : (
      <button
        type="button"
        onClick={advance}
        disabled={!canContinue}
        className="flex min-h-14 w-full items-center justify-center gap-3 rounded-full border-[3px] border-[#ffd23f] bg-[#1d2b4f] px-6 text-lg font-extrabold text-white shadow-[0_5px_0_rgba(0,0,0,0.25)] transition hover:bg-[#263a69] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#ffd23f]/60 disabled:cursor-not-allowed disabled:border-gray-300 disabled:bg-gray-200 disabled:text-gray-700 disabled:shadow-none"
      >
        {currentIsBlocking && !currentSettled ? (
          t("answerToContinue")
        ) : (
          <>
            {t("next")}
            <PlayIcon />
          </>
        )}
      </button>
    );

  const chapterHeading =
    !singleChapter && current ? text(current.chapterTitle, target, home) : undefined;

  return (
    <div ref={rootRef} className={embedded ? "mx-auto max-w-2xl" : "mx-auto max-w-2xl px-4 pb-32"}>
      {/* Header: title, chapter, running score and the two switches. */}
      <header
        className={
          embedded
            ? "mb-3"
            : "sticky top-0 z-10 -mx-4 mb-3 border-b border-[#1d2b4f]/10 bg-white/95 px-4 py-3 backdrop-blur"
        }
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {/* Standalone weeks say where they sit; the lesson page already does. */}
            {!embedded ? (
              <p className="truncate text-xs uppercase tracking-wide text-gray-600">
                {[course.course, course.unit, t("week", { week: course.week })].filter(Boolean).join(" · ")}
              </p>
            ) : null}
            <TitleTag className={`font-bold text-gray-900 ${embedded ? "text-base" : "truncate text-lg"}`}>
              {text(singleChapter ? singleChapter.title : story.title, target, home)}
            </TitleTag>
            {chapterHeading ? (
              <ChapterTag className="truncate text-sm font-bold text-amber-800">{chapterHeading}</ChapterTag>
            ) : null}
          </div>
          <div className="shrink-0 rounded-2xl border-2 border-[#ffd23f] bg-[#fff8db] px-3 py-1 text-right">
            <p className="font-extrabold text-[#1d2b4f]" aria-live="polite">
              {points}
              {maxPoints ? <span className="text-gray-600">/{maxPoints}</span> : null}
            </p>
            <p className="text-xs text-gray-700">{unitLabel}</p>
          </div>
        </div>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={toggleBilingual}
            aria-pressed={bilingual}
            title={t("bilingualToggle")}
            className="min-h-11 min-w-11 rounded-lg border border-gray-300 px-3 text-sm text-gray-700 hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <span className="sr-only">{t("bilingualToggle")}: </span>
            {bilingual ? `${target.toUpperCase()} + ${home.toUpperCase()}` : target.toUpperCase()}
          </button>
          <button
            type="button"
            onClick={toggleSound}
            aria-pressed={soundOn}
            aria-label={t("soundToggle")}
            title={t("soundToggle")}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-gray-300 px-3 text-gray-700 hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            {soundOn ? <Volume2 className="h-5 w-5" aria-hidden="true" /> : <VolumeX className="h-5 w-5" aria-hidden="true" />}
          </button>
        </div>
      </header>

      {/* The stage, and under it (or on it, when there is room) the step. */}
      <div ref={frameRef} className={styles.frame} data-testid="story-stage">
        <div className={`${styles.box} shadow-[0_6px_0_rgba(29,43,79,0.18)]`} onClick={onStageTap}>
          <div key={`${current?.chapterId ?? ""}:${current?.placeRun ?? 0}`} className={`${styles.scene} ${styles.iris}`}>
            <Backdrop placeId={placeId} theme={theme} url={backdropUrl} />
            {titleCard}
            {ribbonTitle ? <PlaceRibbon label={text(ribbonTitle, target, home)} lang={target} /> : null}
            <div className={styles.layer}>{characters}</div>
          </div>
          {celebrating && maxPoints > 0 ? (
            <div
              className={`${styles.popIn} absolute left-1/2 top-[5%] z-[25] -translate-x-1/2 rounded-2xl border-[3px] border-[#ffd23f] px-5 py-2 text-center`}
              style={{ background: "rgb(29 43 79 / 0.92)" }}
              aria-hidden="true"
            >
              <p className={`${styles.titleText} ${styles.subtitleSize} font-black`}>{t("bravo")}</p>
              <StarRow stars={stars} max={3} size={30} />
            </div>
          ) : null}
          {celebrating ? <Confetti seed={7} pieces={60} /> : null}
          {bursts > 0 && !celebrating ? <Confetti key={bursts} seed={bursts} /> : null}
          {story.art?.status === "pending" ? (
            <p className="absolute bottom-[2%] right-[2%] z-[26] rounded-full bg-white/85 px-2 py-0.5 text-[11px] font-semibold text-gray-800">
              {t("artPending")}
            </p>
          ) : null}
        </div>
        <div className={styles.dialogue} aria-live="polite" onClick={onStageTap}>
          {startCard ?? panel}
        </div>
      </div>

      {finishSummary}

      {embedded ? (
        <div ref={controlsRef} className={nextButton ? "mt-4" : ""}>
          {nextButton}
        </div>
      ) : nextButton ? (
        // On phones the bar sits above the bottom navigation (h-16, z-50),
        // which would otherwise cover it.
        <div
          data-testid="story-controls-bar"
          className="fixed inset-x-0 bottom-16 z-40 border-t border-gray-200 bg-white/95 p-3 backdrop-blur md:bottom-0"
        >
          <div className="mx-auto max-w-2xl" ref={controlsRef}>
            {nextButton}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MissingRef({ kind, refId }: { kind: string; refId?: string }): ReactNode {
  const t = useTranslations("Story");
  return (
    <p className={`${styles.panel} ${styles.card} rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800`}>
      {t("missingRef", { kind, ref: refId ?? "?" })}
    </p>
  );
}
