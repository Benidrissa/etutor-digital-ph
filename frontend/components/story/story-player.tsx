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

import { ChevronLeft, Images, Speech, Volume2, VolumeX } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type TouchEvent,
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
import type { Prop, Step, StoryCourse } from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { MinigameView } from "./minigame";
import { QuestionCard, type QuestionAnswer, type QuestionProgress } from "./question-card";
import { Backdrop } from "./stage/backdrop";
import {
  FIGURE_HEIGHT,
  GROUND,
  artFor,
  buildActors,
  heroVariants,
  poseFor,
  safeArtUrl,
  slotsFor,
  type Pose,
} from "./stage/cast";
import { Confetti, StarRow } from "./stage/confetti";
import { CreditsSheet, creditsFor } from "./stage/credits-sheet";
import { LookCloser } from "./stage/look-closer";
import {
  CaptionBar,
  Chalkboard,
  SpeechBubble,
  StageCard,
  VisualPanel,
  type SkipHandle,
  type Standing,
} from "./stage/panels";
import { PaperExercise } from "./stage/paper-exercise";
import { placeLook, placeTheme, placeTitle } from "./stage/places";
import {
  choicesKeyFor,
  readChoices,
  readReadAloud,
  readSoundOn,
  useReducedMotion,
  writeChoices,
  writeReadAloud,
  writeSoundOn,
  type StoryChoices,
} from "./stage/prefs";
import {
  closeUpProp,
  isScenery,
  layoutProps,
  pictureFor,
  placementOf,
  propLabel,
  savesData,
  sizeOf,
  tokenFor,
  type OnStageProp,
} from "./stage/props";
import { planSteps, presenterOf, reactorOf, type PlannedStep } from "./stage/scene-plan";
import { reveal } from "./stage/scroll";
import { playSfx, unlockAudio, type Sfx } from "./stage/sound";
import { speak, speechAvailable, stopSpeaking, type SpeechVoice } from "./stage/speech";
import { StageCharacter, preloadImages, type Gesture } from "./stage/stage-character";
import { StageProp } from "./stage/stage-prop";
import styles from "./stage/stage.module.css";
import { PlaceRibbon, PlayIcon, StartCard, TitleCard } from "./stage/title-card";
import type { TypedHandle } from "./stage/typed-text";

/** A step the learner must deal with before the story moves on. */
const BLOCKING: ReadonlySet<string> = new Set(["ask", "game", "photo"]);

/** How a step that asked something was settled: shown again, never scored again. */
export interface StepRecord {
  points: number;
  question?: QuestionAnswer;
}

/** A swipe to the right on the stage (a phone's "back"): far enough, and flat. */
const SWIPE_MIN_PX = 60;
const SWIPE_MAX_DRIFT_PX = 40;

/** Steps whose panel a tap on the stage may carry past. */
const TAP_THROUGH: ReadonlySet<string> = new Set(["say", "narrate", "concept", "show", "video"]);

/** Steps that put a panel on the stage with a pop. */
const POP_STEPS: ReadonlySet<string> = new Set(["concept", "show", "ask", "game", "photo", "video"]);

const NARRATOR: SpeechVoice = { pitch: 1, rate: 0.95 };

/**
 * How long a chapter's title card stays up on its own before the first line,
 * when that line would otherwise appear under or over it.
 */
export const TITLE_BEAT_MS = 1700;

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
  /**
   * Fires when the learner starts the story from the start card, with their
   * choices (the friend's name, the hero's look). The module story panel uses
   * it to put the friend's name in its own headings.
   */
  onStart?: (choices: StoryChoices) => void;
  /**
   * Previous on the first line (#2688): the host goes back into the chapter
   * before. Without it, Previous stops at the first line.
   */
  onBackFromStart?: () => void;
  /**
   * Open a chapter already completed at its last line, as it was left: what
   * was answered stays answered, nothing is scored or reported again, and
   * nothing is cheered again. The host shows its own end card.
   */
  review?: PlayerSnapshot;
  /** Every change of what was answered, so the host can hand it back as `review`. */
  onSnapshot?: (snapshot: PlayerSnapshot) => void;
}

/** How far a player got and how each step was answered (#2688). */
export interface PlayerSnapshot {
  records: Array<[number, StepRecord]>;
  points: number;
}

export function StoryPlayer({
  course,
  variant = "page",
  onComplete,
  active = true,
  chapterId,
  maxPoints: maxPointsOverride,
  hideFinishSummary = false,
  onStart,
  onBackFromStart,
  review,
  onSnapshot,
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

  // Two switches, remembered per browser: sound effects (on by default) and
  // read-aloud (off by default: a screen reader already speaks each line).
  const [soundOn, setSoundOn] = useState(readSoundOn);
  const [readAloud, setReadAloud] = useState(readReadAloud);
  const [speechWorks] = useState(speechAvailable);
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
  };
  const toggleReadAloud = () => {
    const next = !readAloud;
    setReadAloud(next);
    writeReadAloud(next);
    if (!next) stopSpeaking();
  };

  // The learner's choices at the start of a course's story (#2672): the
  // friend's name and which hero they are. Asked once per course and browser.
  const courseKey = choicesKeyFor(course);
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
  // The things the story talks about (#2681), and their pictures.
  const propsById = useMemo(
    () =>
      new Map(
        (Array.isArray(story.props) ? story.props : [])
          .filter((prop): prop is Prop => !!prop && typeof prop.id === "string" && !!prop.id)
          .map((prop) => [prop.id, prop]),
      ),
    [story.props],
  );
  const propMedia = story.art?.props;
  const propContext = useMemo(() => ({ props: propsById, media: propMedia }), [propsById, propMedia]);
  const flat = useMemo<PlannedStep[]>(
    () => planSteps(chapters, story.chapters ?? [], actors, propContext),
    [chapters, story.chapters, actors, propContext],
  );
  const figureLang = figureLanguage(target, home);
  const credits = useMemo(() => creditsFor(story, figureLang), [story, figureLang]);

  const questions = useMemo(() => new Map((story.questions ?? []).map((q) => [q.id, q])), [story.questions]);
  const exercises = useMemo(() => new Map((story.exercises ?? []).map((e) => [e.id, e])), [story.exercises]);
  const games = useMemo(() => new Map((story.minigames ?? []).map((g) => [g.id, g])), [story.minigames]);
  const videos = useMemo(() => new Map((story.videos ?? []).map((v) => [v.id, v])), [story.videos]);

  const maxPoints =
    maxPointsOverride !== undefined
      ? Math.max(0, Number(maxPointsOverride) || 0)
      : Number(story.checks?.max_points ?? 0);
  const unitLabel = text(story.rewards?.unit, target, home) || t("pointsUnit");

  // A chapter reviewed (Previous from the next one) opens at its last line,
  // as it was left.
  const [reviewing] = useState(() => !!review && flat.length > 0);
  const [initial] = useState(() => {
    const records = new Map<number, StepRecord>(
      reviewing ? (review?.records ?? []).filter(([at]) => at >= 0 && at < flat.length) : [],
    );
    return { index: reviewing ? flat.length - 1 : 0, records, points: reviewing ? (review?.points ?? 0) : 0 };
  });
  const [index, setIndex] = useState(initial.index);
  // The furthest step reached. Previous walks back through what was played
  // (#2682); Next walks forward again up to here without replaying anything.
  const [furthest, setFurthest] = useState(initial.index);
  // The step that is on screen for the first time, or -1 after Previous: a
  // step seen again is shown at once, with no typing, title beat or sound.
  const [fresh, setFresh] = useState(reviewing ? -1 : 0);
  const revisit = index !== fresh;
  const [points, setPoints] = useState(initial.points);
  const [settledSteps, setSettledSteps] = useState<Set<number>>(() => new Set(initial.records.keys()));
  // Mirrors settledSteps synchronously so a step can only ever score once,
  // even if a child reports twice before React re-renders.
  const settledRef = useRef<Set<number>>(new Set(initial.records.keys()));
  // How each settled step was answered, to show it again read-only.
  const [records, setRecords] = useState<ReadonlyMap<number, StepRecord>>(initial.records);
  // A question left half-answered (a wrong first try, its hint), so Previous
  // then Next cannot hand out a fresh first try (#2688).
  const [pending, setPending] = useState<ReadonlyMap<number, QuestionProgress>>(() => new Map());
  // The step whose timed game is running: Previous waits for it to end.
  const [gameRunning, setGameRunning] = useState<number | null>(null);
  // The hero's reaction to the latest answer on the current step.
  const [reaction, setReaction] = useState<{ index: number; correct: boolean; n: number } | null>(null);
  const [bursts, setBursts] = useState(0);

  // A chapter's title card is a beat of its own when its first line is not a
  // narrator's caption (which sits clear of it), or when props pop onto the
  // stage with that line: the card shows alone, then fades on a timer or at
  // the first Next, and only then does the line come (with its props).
  const beatAt = useCallback(
    (stepIndex: number) => {
      const item = flat[stepIndex];
      return item?.startsChapter && (item.step.type !== "narrate" || item.entering.length > 0) ? stepIndex : null;
    },
    [flat],
  );
  const [titleBeat, setTitleBeat] = useState<number | null>(() =>
    choices === null || reviewing ? null : beatAt(0),
  );
  // Started from the start card: the title was on screen with it already.
  const [startedFromIntro, setStartedFromIntro] = useState(false);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const dialogueRef = useRef<HTMLDivElement | null>(null);
  const controlsRef = useRef<HTMLDivElement | null>(null);
  const nextButtonRef = useRef<HTMLButtonElement | null>(null);
  const typedRef = useRef<TypedHandle | null>(null);
  const boardRef = useRef<SkipHandle | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Bring the step's text into view, between the app's real bars (measured,
  // see ./stage/scroll). Embedded, down to the Next button under it. The
  // dialogue box is measured, not the panel in it: a new panel pops in from
  // scale(0.6), and measured mid-pop it looks shorter and lower than it is,
  // so a tall card would end up under the header (#2688). On a wide stage
  // the box is the stage itself.
  const revealStep = useCallback(() => {
    requestAnimationFrame(() => {
      reveal(dialogueRef.current, { to: embedded ? controlsRef.current : undefined, smooth: !reducedMotion });
    });
  }, [embedded, reducedMotion]);

  useEffect(() => {
    if (titleBeat === null) return;
    const timer = setTimeout(() => {
      setTitleBeat(null);
      revealStep();
    }, TITLE_BEAT_MS);
    return () => clearTimeout(timer);
  }, [titleBeat, revealStep]);

  const advance = useCallback(() => {
    // During a title beat, Next only ends the beat: the first line comes up.
    if (titleBeat !== null) {
      setTitleBeat(null);
      revealStep();
      return;
    }
    const next = Math.min(index + 1, flat.length - 1);
    setIndex(next);
    if (next > furthest) {
      setFurthest(next);
      setFresh(next);
      setTitleBeat(beatAt(next));
    } else {
      setTitleBeat(null);
    }
    revealStep();
  }, [titleBeat, index, furthest, flat.length, beatAt, revealStep]);

  // One line back, across scenes and chapters, never to the start card or a
  // title beat. What was answered is shown answered. On the first line, the
  // host may take the learner into the chapter before.
  const goBack = useCallback(() => {
    if (index <= 0) {
      onBackFromStart?.();
      return;
    }
    setIndex(index - 1);
    setFresh(-1);
    setTitleBeat(null);
    // An answer seen again is not cheered (or sighed over) again.
    setReaction(null);
    revealStep();
    // The control that had the focus may now be disabled (Previous on the
    // first line) or gone (a card of the step left): keep the keyboard in
    // the story instead of dropping it to the top of the page.
    requestAnimationFrame(() => {
      const focused = document.activeElement as HTMLElement | null;
      const lost =
        !focused ||
        focused === document.body ||
        (focused as HTMLButtonElement).disabled ||
        !rootRef.current?.contains(focused);
      if (!lost) return;
      const next = nextButtonRef.current;
      (next && !next.disabled ? next : dialogueRef.current)?.focus();
    });
  }, [index, revealStep, onBackFromStart]);

  const settle = useCallback((stepIndex: number, earned: number, record?: Omit<StepRecord, "points">) => {
    if (settledRef.current.has(stepIndex)) return;
    settledRef.current.add(stepIndex);
    setPoints((total) => total + earned);
    setSettledSteps(new Set(settledRef.current));
    setRecords((previous) => new Map(previous).set(stepIndex, { points: earned, ...record }));
    setPending((previous) => {
      if (!previous.has(stepIndex)) return previous;
      const next = new Map(previous);
      next.delete(stepIndex);
      return next;
    });
  }, []);

  // Hand what was answered to the host, to come back to it later.
  const onSnapshotRef = useRef(onSnapshot);
  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);
  useEffect(() => {
    onSnapshotRef.current?.({ records: [...records], points });
  }, [records, points]);

  const current = flat[index];
  const currentIsBlocking = current ? BLOCKING.has(current.step.type) : false;
  const currentSettled = settledSteps.has(index);
  const lastIndex = flat.length - 1;
  const atEnd = index >= lastIndex;
  const canContinue = !introOpen && !atEnd && (!currentIsBlocking || currentSettled);
  const beatOn = titleBeat !== null && titleBeat === index;
  // Next works during a title beat (it brings the first line up), even when
  // that line is a question still to answer.
  const nextEnabled = beatOn || canContinue;
  // The end is reached once the last step is on screen and, if it asks
  // something of the learner, answered.
  const finished =
    flat.length > 0 &&
    atEnd &&
    (!BLOCKING.has(flat[lastIndex].step.type) || settledSteps.has(lastIndex));
  // A chapter that was actually played through gets a cheer; one that is
  // complete the moment it opens (a one-line checkpoint) does not, and nor
  // does one opened again to look back at it.
  const celebrating = finished && !introOpen && !reviewing && (index > 0 || settledSteps.size > 0);
  // Previous, ← and a swipe: back one line, or into the chapter before;
  // never out of a timed game that is running (#2688).
  const gameBlocksBack = gameRunning === index && !settledSteps.has(index);
  const canGoBack = !introOpen && !gameBlocksBack && (index > 0 || !!onBackFromStart);

  // Report completion exactly once (a chapter opened again to look back at
  // it was reported already). The callback is read through a ref so a parent
  // re-rendering with a new function cannot re-fire it.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);
  const completedRef = useRef(reviewing);
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

  // A whoosh for a new place, a pop for a card or a prop popping in (once the
  // title beat is over). A step seen again is quiet.
  const lastPlaceRun = useRef<number | null>(null);
  useEffect(() => {
    if (!current || introOpen || beatOn) return;
    const quiet = revisit;
    if (lastPlaceRun.current !== null && lastPlaceRun.current !== current.placeRun) {
      if (!quiet) sfx("whoosh");
    } else if (!quiet && (POP_STEPS.has(current.step.type) || current.entering.length > 0)) sfx("pop");
    lastPlaceRun.current = current.placeRun;
  }, [current, introOpen, beatOn, revisit, sfx]);

  // Ambient motion stands still while the stage is out of sight. Several
  // changes can come in one batch: the last one is the state now.
  const [onScreen, setOnScreen] = useState(true);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[entries.length - 1];
      setOnScreen(entry?.isIntersecting ?? true);
    });
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);
  const paused = !active || !onScreen;

  // Who is on stage now, and who does what.
  const cast = current?.cast ?? [];
  const slots = slotsFor(cast.length);
  const reactor = reactorOf(cast, actors);
  const presenter = presenterOf(cast, actors);
  const step = current?.step;
  const speakerId = step?.type === "say" ? step.who : step?.type === "concept" ? presenter : undefined;

  // Read-aloud: the step's target-language text, in its speaker's voice. It
  // is keyed as a string (with the step's index, so a repeated line is read
  // again) and parsed back in the effect, which then runs once per step.
  const speechKey = (() => {
    if (!step) return null;
    const targetLine = lineOf(stepText(step, target));
    const homeLine = lineOf(stepText(step, home));
    const lang = targetLine ? target : home;
    const voiceOf = (id: string | undefined) => (id ? actors.get(id)?.voice : undefined) ?? NARRATOR;
    let speech: { lines: string[]; lang: string; voice: SpeechVoice } | null = null;
    switch (step.type) {
      case "say":
        speech = { lines: [targetLine || homeLine], lang, voice: voiceOf(step.who) };
        break;
      case "narrate":
        speech = { lines: [targetLine || homeLine], lang, voice: NARRATOR };
        break;
      case "concept": {
        const rows = rowsOf(step, target).length ? rowsOf(step, target) : rowsOf(step, home);
        const title = step.title ? text(step.title, target, home) : "";
        speech = { lines: [title, ...rows], lang, voice: voiceOf(presenter) };
        break;
      }
      case "show": {
        // A close-up says its caption, else the picture's, else the thing's name.
        const closeUp = closeUpProp(step);
        const prop = closeUp ? propsById.get(closeUp) : undefined;
        const picture = prop ? pictureFor(prop, propMedia?.[prop.id], figureLang) : undefined;
        const words = step.caption
          ? text(step.caption, target, home)
          : picture?.caption
            ? text(picture.caption, target, home)
            : prop
              ? propLabel(prop, target, home)
              : "";
        if (words) speech = { lines: [words], lang: target, voice: NARRATOR };
        break;
      }
      case "ask": {
        const question = step.ref ? questions.get(step.ref) : undefined;
        if (question) speech = { lines: [text(question.prompt, target, home)], lang: target, voice: NARRATOR };
        break;
      }
      case "game": {
        const game = step.ref ? games.get(step.ref) : undefined;
        if (game) {
          speech = {
            lines: [text(game.title, target, home), text(game.instruction, target, home)],
            lang: target,
            voice: NARRATOR,
          };
        }
        break;
      }
    }
    return speech ? JSON.stringify({ index, ...speech }) : null;
  })();

  useEffect(() => {
    if (!readAloud || !active || introOpen || beatOn || !speechKey) return;
    const speech = JSON.parse(speechKey) as { lines: string[]; lang: string; voice: SpeechVoice };
    speak(speech.lines, speech.lang, speech.voice);
    return () => stopSpeaking();
  }, [speechKey, readAloud, active, introOpen, beatOn]);

  // Only the poses of the cast on stage are fetched ahead: the whole story's
  // art is too much for a 3G link.
  const stageIds = (introOpen ? flat[0]?.cast : current?.cast) ?? [];
  const stageKey = stageIds.join(",");
  useEffect(() => {
    const urls: Array<string | undefined> = [];
    for (const id of stageKey ? stageKey.split(",") : []) {
      const actor = actors.get(id);
      if (!actor) continue;
      for (const pose of ["idle", "talk", "happy", "think"] as const) urls.push(artFor(story.art, actor.artKey, pose));
    }
    preloadImages(urls);
  }, [stageKey, actors, story.art]);

  // The scene's prop drawings, and the next close-up's small picture (never
  // the large one, and not at all when the learner saves data).
  const propPreload = (() => {
    if (!current || introOpen) return "";
    const urls: string[] = [];
    for (const id of current.sceneProps) {
      const prop = propsById.get(id);
      if (!prop) continue;
      const token = tokenFor(prop, propMedia?.[id], placementOf(prop, current.cast));
      if (token.kind === "sticker" || token.kind === "polaroid") urls.push(token.src);
    }
    const nextStep = flat[index + 1]?.step;
    const nextCloseUp = nextStep ? closeUpProp(nextStep) : undefined;
    const nextProp = nextCloseUp ? propsById.get(nextCloseUp) : undefined;
    if (nextProp && !savesData()) {
      const picture = pictureFor(nextProp, propMedia?.[nextProp.id], figureLang);
      if (picture) urls.push(picture.src);
    }
    return urls.join("\n");
  })();
  useEffect(() => {
    if (propPreload) preloadImages(propPreload.split("\n"));
  }, [propPreload]);

  // A close-up opened by tapping a prop, for the step it was opened on, and
  // the image credits; the opener gets the focus back when they close.
  const [looking, setLooking] = useState<{ id: string; index: number } | null>(null);
  const [creditsOpen, setCreditsOpen] = useState(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const lookingProp = looking && looking.index === index ? propsById.get(looking.id) : undefined;
  const dialogOpen = !!lookingProp || creditsOpen;
  const openLook = useCallback(
    (prop: Prop, trigger: HTMLElement) => {
      openerRef.current = trigger;
      setLooking({ id: prop.id, index });
    },
    [index],
  );
  const closeDialog = useCallback(() => {
    setLooking(null);
    setCreditsOpen(false);
    requestAnimationFrame(() => openerRef.current?.focus());
  }, []);

  // Space and → move on, like the Next button, and ← goes back, like
  // Previous, when the story has the focus (or nothing does) and the key is
  // not meant for a field or a button. The key is only taken from the page
  // when it did move the story.
  const tryAdvanceRef = useRef<() => boolean>(() => false);
  const tryBackRef = useRef<() => boolean>(() => false);
  useEffect(() => {
    tryAdvanceRef.current = () => {
      if (!nextEnabled || dialogOpen) return false;
      advance();
      return true;
    };
    tryBackRef.current = () => {
      if (!canGoBack || dialogOpen) return false;
      goBack();
      return true;
    };
  }, [nextEnabled, advance, canGoBack, dialogOpen, goBack]);
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
      if (event.key !== " " && event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      // A dialog over the page (a full-screen figure, a close-up, the
      // credits) has the keys, even when the focus fell to the page.
      if (document.querySelector('[aria-modal="true"]')) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
      // A focused button already answers Space itself.
      if (event.key === " " && target?.closest("button, a, summary, [role=button]")) return;
      if (target && target !== document.body && !rootRef.current?.contains(target)) return;
      const moved = event.key === "ArrowLeft" ? tryBackRef.current() : tryAdvanceRef.current();
      if (moved) event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  // A swipe to the right on the stage or its text goes back one line, like
  // turning back a page. The tap a swipe ends with is not a tap.
  //
  // Events from a portal (the full-screen figure viewer is rendered in the
  // page body but is a React child of the step) still bubble here through
  // React: only events whose target is really inside the stage count (#2688).
  const fromPortal = (event: MouseEvent | TouchEvent) =>
    !(event.currentTarget as Element).contains(event.target as Node);
  const swipeRef = useRef<{ x: number; y: number } | null>(null);
  const swipedAtRef = useRef(0);
  const onTouchStart = (event: TouchEvent) => {
    if (fromPortal(event)) {
      swipeRef.current = null;
      return;
    }
    const touch = event.touches[0];
    swipeRef.current = event.touches.length === 1 && touch ? { x: touch.clientX, y: touch.clientY } : null;
  };
  const onTouchEnd = (event: TouchEvent) => {
    const start = swipeRef.current;
    swipeRef.current = null;
    if (fromPortal(event)) return;
    const touch = event.changedTouches[0];
    if (!start || !touch) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (dx < SWIPE_MIN_PX || Math.abs(dy) > SWIPE_MAX_DRIFT_PX) return;
    if (event.target instanceof Element && event.target.closest("input, textarea, select")) return;
    swipedAtRef.current = event.timeStamp;
    tryBackRef.current();
  };

  // A tap on the stage finishes the line being typed, then moves on. Never
  // while a question, a game or a paper exercise is waiting.
  const onStageTap = (event: MouseEvent) => {
    if (introOpen || !current) return;
    if (dialogOpen || fromPortal(event)) return;
    if (swipedAtRef.current && event.timeStamp - swipedAtRef.current < 600) return;
    if (event.target instanceof Element && event.target.closest("button, a, input, select, textarea, label")) return;
    if (beatOn) {
      advance();
      return;
    }
    if (finished || !TAP_THROUGH.has(current.step.type)) return;
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
    setStartedFromIntro(true);
    sfx("whoosh");
    onStart?.(next);
    // The start card is gone: carry the keyboard on to the Next button, or to
    // the first step when it is a question (Next waits for the answer).
    requestAnimationFrame(() => {
      const button = nextButtonRef.current;
      if (button && !button.disabled) button.focus();
      else dialogueRef.current?.focus();
    });
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
  // The title card never shares the stage with a speech bubble or a card:
  // with the start card, alone during its beat, or above a narrator's caption
  // (which sits at the bottom). After the start card it has been seen. Nor
  // does it share it with props (#2688): they stand over it, and they move
  // the caption to the top, so a narrated opener with props shows its title
  // during its beat only.
  const showTitle =
    introOpen ||
    beatOn ||
    (!!current?.startsChapter &&
      step?.type === "narrate" &&
      current.props.length === 0 &&
      !(startedFromIntro && index === 0));
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
    // A close-up of the thing everyone is talking about: the hero is amazed.
    if (step.type === "show" && closeUpProp(step) && id === reactor) return "surprised";
    return "idle";
  };

  const speakingLine = step && speakerId ? lineOf(stepText(step, target)) || lineOf(stepText(step, home)) : "";
  const speakBeats = Math.max(2, Math.min(40, Math.round(lineSeconds(speakingLine, readAloud) / 0.42)));

  const characters = stageCast.map((id, slot) => {
    const actor = actors.get(id);
    if (!actor) return null;
    const pose = beatOn ? "idle" : poseOf(id);
    const speaking = !introOpen && !beatOn && !celebrating && id === speakerId;
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
        still={reducedMotion || paused}
      />
    );
  });

  // The props on stage (#2681): none with the start card or under a title
  // beat, so they pop in with the line that brings them.
  const propIds = introOpen || beatOn || !current ? [] : current.props;
  const onStageProps: OnStageProp[] = propIds.flatMap((id) => {
    const prop = propsById.get(id);
    if (!prop) return [];
    const placement = placementOf(prop, cast);
    return [{ prop, placement, size: sizeOf(prop, placement) }];
  });
  const propSlots = layoutProps(
    onStageProps,
    cast.flatMap((id, slot) => {
      const actor = actors.get(id);
      return actor ? [{ id, x: slots[slot], height: FIGURE_HEIGHT[actor.figure] }] : [];
    }),
  );
  const propViews = onStageProps.flatMap((item) => {
    const slot = propSlots.get(item.prop.id);
    if (!slot || !current) return [];
    const media = propMedia?.[item.prop.id];
    const hasCloseUp = !!pictureFor(item.prop, media, figureLang);
    return [
      {
        scenery: isScenery(item.placement),
        node: (
          <StageProp
            key={item.prop.id}
            prop={item.prop}
            token={tokenFor(item.prop, media, item.placement)}
            slot={slot}
            label={propLabel(item.prop, target, home)}
            lang={target}
            entering={!revisit && current.entering.includes(item.prop.id)}
            pointed={current.pointed.includes(item.prop.id)}
            bounceKey={String(index)}
            still={reducedMotion || paused}
            onOpen={hasCloseUp ? openLook : undefined}
          />
        ),
      },
    ];
  });
  // Something stands in front of the cast's feet: on a wide stage the
  // narrator's caption goes to the top, so it never hides it. Unless
  // something is in the sky, which the top caption would hide (#2688).
  const propsInFront =
    onStageProps.some((item) => !isScenery(item.placement)) &&
    !onStageProps.some((item) => item.placement === "sky");

  // Where everyone stands, for the bubble to keep clear of other faces.
  const standing = (id: string): Standing | undefined => {
    const slot = cast.indexOf(id);
    const actor = actors.get(id);
    return slot >= 0 && actor ? { x: slots[slot], height: FIGURE_HEIGHT[actor.figure] } : undefined;
  };
  // The chalkboard hangs away from the teacher presenting it; a teacher in
  // the middle gets a board that stops above their head.
  const presenterSlot = step?.type === "concept" && presenter ? standing(presenter) : undefined;
  const boardSide: "left" | "right" | "center" = !presenterSlot
    ? "center"
    : presenterSlot.x < 38
      ? "right"
      : presenterSlot.x > 62
        ? "left"
        : "center";
  const boardMax =
    presenterSlot && boardSide === "center" ? Math.max(30, 100 - GROUND - presenterSlot.height - 6) : undefined;

  /* ---- The step's panel ------------------------------------------------ */

  const panel = (() => {
    if (!current || !step) return null;
    const targetLine = lineOf(stepText(step, target));
    const homeLine = lineOf(stepText(step, home));
    const primary = targetLine || homeLine;
    const primaryLang = targetLine ? target : home;
    const secondary = bilingual && !!targetLine && !!homeLine && homeLine !== targetLine ? homeLine : undefined;
    // A line seen again (Previous) is shown whole at once.
    const animate = !reducedMotion && !revisit;
    const record = records.get(index);
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
            at={propsInFront ? "top" : "bottom"}
            eyebrow={propsInFront && ribbonTitle ? text(ribbonTitle, target, home) : undefined}
          />
        );
      case "say": {
        const actor = step.who ? actors.get(step.who) : undefined;
        return (
          <SpeechBubble
            key={index}
            name={actor?.name ?? step.who ?? ""}
            aiLabel={actor?.isTutor ? t("aiLabel") : undefined}
            actor={actor}
            speaker={step.who ? standing(step.who) : undefined}
            others={cast.filter((id) => id !== step.who).flatMap((id) => standing(id) ?? [])}
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
            rowDelays={reducedMotion || revisit ? rows.map(() => 0) : rowDelays(rows, title, readAloud)}
            side={boardSide}
            maxHeight={boardMax}
          />
        );
      }
      case "show": {
        // A close-up of a prop (#2681): its picture, caption and credit.
        const closeUp = closeUpProp(step);
        if (closeUp) {
          const prop = propsById.get(closeUp);
          if (!prop) return null;
          const media = propMedia?.[closeUp];
          return (
            <VisualPanel key={index}>
              <LookCloser
                variant="step"
                prop={prop}
                picture={pictureFor(prop, media, figureLang)}
                stickerUrl={media?.sticker}
                caption={step.caption}
                target={target}
                home={home}
                bilingual={bilingual}
                headingLevel={embedded ? 4 : 3}
              />
            </VisualPanel>
          );
        }
        return (
          <VisualPanel key={index}>
            <ConceptVisual
              visual={step.visual ?? "unknown"}
              params={step.params}
              caption={step.caption ? text(step.caption, target, home) : undefined}
              language={figureLang}
            />
          </VisualPanel>
        );
      }
      case "ask": {
        const question = step.ref ? questions.get(step.ref) : undefined;
        if (!question) return <MissingRef key={index} kind="question" refId={step.ref} />;
        return (
          <StageCard key={index} ref={cardRef} kind="ask" banner={t("questionBanner")} paper review={!!record}>
            <QuestionCard
              question={question}
              target={target}
              home={home}
              bilingual={bilingual}
              rewards={story.rewards}
              className="pt-2"
              review={record?.question}
              resume={pending.get(index)}
              onProgress={(progress) => setPending((previous) => new Map(previous).set(index, progress))}
              onAnswered={(outcome) =>
                settle(index, outcome.points, {
                  question: {
                    answer: outcome.answer,
                    parts: outcome.parts,
                    correct: outcome.correct,
                    points: outcome.points,
                    attempts: outcome.attempts,
                  },
                })
              }
              onAttempt={onAttempt(index)}
            />
          </StageCard>
        );
      }
      case "game": {
        const game = step.ref ? games.get(step.ref) : undefined;
        if (!game) return <MissingRef key={index} kind="mini-game" refId={step.ref} />;
        return (
          <StageCard
            key={index}
            ref={cardRef}
            kind="game"
            banner={t("gameBanner")}
            bannerColor="#c2410c"
            review={!!record}
          >
            <MinigameView
              game={game}
              target={target}
              home={home}
              bilingual={bilingual}
              active={active && !introOpen}
              className="pt-2"
              result={record?.points}
              // The round's counter, clock, prompt and targets in view: on a
              // short phone they come before the card's banner (#2688).
              onRound={(round, targets) => reveal(round, { to: targets, smooth: !reducedMotion })}
              onPhase={(phase) => setGameRunning(phase === "playing" ? index : null)}
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
          <StageCard key={index} kind="photo" review={!!record}>
            <PaperExercise
              exercise={exercise}
              label={story.module_story ? chapterLocalId(exercise.id) : exercise.id}
              target={target}
              home={home}
              bilingual={bilingual}
              settled={currentSettled}
              awardedBefore={record?.points}
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
        {credits.length > 0 ? (
          <button
            type="button"
            onClick={(event) => {
              openerRef.current = event.currentTarget;
              setCreditsOpen(true);
            }}
            className="mt-2 inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-sm font-semibold text-sky-100 underline hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd23f]"
          >
            <Images className="h-4 w-4" aria-hidden="true" />
            {t("imageCredits")}
          </button>
        ) : null}
      </div>
    ) : null;

  const nextButton =
    finished || introOpen ? null : (
      <button
        ref={nextButtonRef}
        type="button"
        onClick={advance}
        disabled={!nextEnabled}
        className="flex min-h-14 min-w-0 flex-1 items-center justify-center gap-3 rounded-full border-[3px] border-[#ffd23f] bg-[#1d2b4f] px-4 text-base leading-tight font-extrabold min-[360px]:text-lg text-white shadow-[0_5px_0_rgba(0,0,0,0.25)] transition hover:bg-[#263a69] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#1d6fb8] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:border-gray-300 disabled:bg-gray-200 disabled:text-gray-700 disabled:shadow-none sm:px-6"
      >
        {currentIsBlocking && !currentSettled && !beatOn ? (
          t("answerToContinue")
        ) : (
          <>
            {t("next")}
            <PlayIcon />
          </>
        )}
      </button>
    );

  // « Précédent », next to « Suite » (#2682): one line back, across scenes and
  // chapters; nothing to go back to on the first line.
  const previousButton =
    introOpen || (flat.length < 2 && !onBackFromStart) ? null : (
      <button
        type="button"
        onClick={goBack}
        disabled={!canGoBack}
        className="flex min-h-14 shrink-0 items-center justify-center gap-1 rounded-full border-[3px] border-[#1d2b4f] bg-white min-w-14 px-3 text-base min-[360px]:pl-2 min-[360px]:pr-4 font-extrabold text-[#1d2b4f] shadow-[0_5px_0_rgba(0,0,0,0.15)] transition hover:bg-[#fff8db] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#1d6fb8] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:border-gray-300 disabled:text-gray-500 disabled:shadow-none"
      >
        <ChevronLeft className="h-6 w-6" aria-hidden="true" />
        {/* On a 320px phone the arrow alone, so « Suite » keeps one line. */}
        <span className="max-[359px]:sr-only">{t("previous")}</span>
      </button>
    );
  const controls =
    previousButton || nextButton ? (
      <div className="flex items-stretch gap-2">
        {previousButton}
        {nextButton}
      </div>
    ) : null;

  // Read aloud, the line is spoken already: no second voice from the screen
  // reader. Only when it really is spoken: no speech engine, or nothing to
  // say for this step, leaves the live region on.
  const spoken = readAloud && speechWorks && !!speechKey;

  const chapterHeading =
    !singleChapter && current ? text(current.chapterTitle, target, home) : undefined;

  return (
    <div
      ref={rootRef}
      // On the page, room under the last step for the fixed Next bar and,
      // on phones, the bottom navigation under it.
      className={embedded ? "mx-auto w-full max-w-2xl" : "mx-auto w-full max-w-2xl px-4 pb-44 md:pb-28"}
    >
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
        <div className="mt-2 flex flex-wrap gap-2">
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
            onClick={toggleReadAloud}
            aria-pressed={readAloud}
            className={`flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
              readAloud ? "border-[#1d2b4f] bg-[#fff8db] text-[#1d2b4f]" : "border-gray-300 text-gray-700 hover:border-teal-400"
            }`}
          >
            <Speech className="h-5 w-5" aria-hidden="true" />
            {/* Words from 640px; on a 320px phone the header stays one row. */}
            <span className="sr-only sm:not-sr-only">{t("readAloudToggle")}</span>
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
          {credits.length > 0 ? (
            <button
              type="button"
              onClick={(event) => {
                openerRef.current = event.currentTarget;
                setCreditsOpen(true);
              }}
              aria-label={t("imageCredits")}
              title={t("imageCredits")}
              className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-gray-300 px-3 text-gray-700 hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              <Images className="h-5 w-5" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </header>

      {/* The stage, and under it (or on it, when there is room) the step. */}
      <div
        ref={frameRef}
        className={`${styles.frame} ${paused ? styles.paused : ""}`}
        data-testid="story-stage"
      >
        <div
          className={`${styles.box} shadow-[0_6px_0_rgba(29,43,79,0.18)]`}
          onClick={onStageTap}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          <div key={`${current?.chapterId ?? ""}:${current?.placeRun ?? 0}`} className={`${styles.scene} ${styles.iris}`}>
            <Backdrop placeId={placeId} theme={theme} url={backdropUrl} />
            {titleCard}
            {ribbonTitle ? (
              // On a wide stage with props in front, the caption moves to the
              // top and says where we are itself.
              <div className={propsInFront && step?.type === "narrate" ? styles.narrowOnly : undefined}>
                <PlaceRibbon label={text(ribbonTitle, target, home)} lang={target} />
              </div>
            ) : null}
            <div className={styles.layer}>
              {propViews.filter((view) => view.scenery).map((view) => view.node)}
              {characters}
              {propViews.filter((view) => !view.scenery).map((view) => view.node)}
            </div>
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
        <div
          ref={dialogueRef}
          tabIndex={-1}
          // A timed game sits under the stage at every width (see the stylesheet).
          className={`${styles.dialogue} ${step?.type === "game" && !introOpen ? styles.dialogueFlow : ""} focus:outline-none`}
          aria-live={spoken ? "off" : "polite"}
          onClick={onStageTap}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          {/* During a title beat the first line waits: it is not there to
              type out unseen, nor (a card) to arm itself under the title. */}
          {startCard ?? (beatOn ? null : panel)}
        </div>
      </div>

      {finishSummary}

      {embedded ? (
        <div ref={controlsRef} className={controls ? "mt-4" : ""}>
          {controls}
        </div>
      ) : controls ? (
        // On phones the bar sits above the bottom navigation (h-16, z-50),
        // which would otherwise cover it.
        <div
          data-testid="story-controls-bar"
          className="fixed inset-x-0 bottom-16 z-40 border-t border-gray-200 bg-white/95 p-3 backdrop-blur md:bottom-0"
        >
          <div className="mx-auto max-w-2xl" ref={controlsRef}>
            {controls}
          </div>
        </div>
      ) : null}

      {lookingProp ? (
        <LookCloser
          variant="overlay"
          prop={lookingProp}
          picture={pictureFor(lookingProp, propMedia?.[lookingProp.id], figureLang)}
          stickerUrl={propMedia?.[lookingProp.id]?.sticker}
          target={target}
          home={home}
          bilingual={bilingual}
          onClose={closeDialog}
        />
      ) : null}
      {creditsOpen ? <CreditsSheet entries={credits} target={target} home={home} onClose={closeDialog} /> : null}
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
