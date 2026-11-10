/**
 * Mini-game engines for the story player (format Appendix A.9).
 *
 * Two round shapes are played, through one tapping engine:
 *
 * - items rounds (`catch`, contract C5) — `{prompt, items: [{label, correct,
 *   trap}]}`. Each item says itself whether it is right, which is what a lesson
 *   story needs: "which of these is a sign of dehydration?" has no rule a
 *   client could evaluate. This is the shape lesson stories are generated in.
 * - list rounds (`pop`) — a list of values plus a `rule` such as `is_prime`.
 *   The rule is evaluated in the browser, deliberately: a tap cannot wait for a
 *   round-trip on a 2G connection, and the backend validator has already
 *   recomputed the rule for every target, so the two cannot disagree.
 *
 * Either way the learner taps every right item before the timer runs out;
 * wrong items are the week's traps rather than random noise, and tapping one
 * shows `hint_after_wrong`. Keys 1-6 mirror the touch targets, as A.9 asks,
 * but never while the learner is typing somewhere else on the page (the AI
 * tutor's chat box, say) or holding a shortcut modifier.
 *
 * While `active` is false (the player is hidden but kept mounted, as in a
 * tab) the round's clock stands still and the keys are not listened to, so a
 * learner who looks elsewhere mid-game does not come back to rounds that ran
 * out unseen.
 *
 * Points follow the validator's arithmetic (`per_correct` per right item, a
 * missing or zero `per_correct` counting as 1) so the score a learner sees can
 * reach the `max_points` the backend computed.
 *
 * A game with no round this player can render says so and lets the learner
 * continue, rather than blocking the story on a missing mechanic.
 */

"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useReducer, useRef } from "react";

import { seededShuffle, text } from "@/lib/story-course/answer";
import { isPrime } from "@/lib/story-course/numbers";
import type {
  Minigame,
  MinigameItem,
  MinigameItemsRound,
  TextObject,
} from "@/lib/story-course/types";

interface MinigameViewProps {
  game: Minigame;
  target: string;
  home: string;
  bilingual: boolean;
  /** False while out of sight: the countdown pauses and keys are ignored. */
  active?: boolean;
  onFinished: (outcome: { gameId: string; points: number }) => void;
  /** Each tap on an item, right or wrong: the cartoon stage plays a sound. */
  onTap?: (correct: boolean) => void;
  /** Replaces the game's own frame, for a host that draws one around it. */
  className?: string;
  /**
   * Played already (the story's Previous): shows how it ended, with nothing
   * to play or score again.
   */
  result?: number;
  /**
   * Brings the round into view when it starts: `round` holds its counter,
   * clock and prompt, `targets` the things to tap. A game under the stage can
   * begin below the fold on a laptop, or past the bottom bar on a phone.
   */
  onRound?: (round: HTMLElement, targets: HTMLElement) => void;
  /** Whether the game is waiting, running or over, as it changes. */
  onPhase?: (phase: "ready" | "playing" | "done") => void;
}

/** Rule predicates the player can evaluate locally, for list rounds. */
const RULES: Record<string, (value: number) => boolean> = {
  is_prime: isPrime,
};

/** Seconds per round when the file does not say: items take longer to read. */
const DEFAULT_TIMER_ITEMS_S = 30;
const DEFAULT_TIMER_LIST_S = 20;
/** Pause on a cleared round so the last green tap registers before it moves on. */
const CLEARED_ROUND_DELAY_MS = 600;
/** Keys 1-6 (A.9). */
const KEYED_SLOTS = 6;

/**
 * True when a key press belongs to something else: typing in a field (the AI
 * tutor's chat, a search box), an IME composition, or a shortcut such as
 * Ctrl+1 to switch browser tabs.
 */
function isForeignKeyPress(event: KeyboardEvent): boolean {
  if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return true;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  // isContentEditable, plus the attribute for engines that do not compute it.
  return (
    target.isContentEditable ||
    !!target.closest('[contenteditable]:not([contenteditable="false"])')
  );
}

interface PlayItem {
  label: TextObject | string;
  correct: boolean;
}

interface PlayRound {
  prompt?: TextObject;
  items: PlayItem[];
}

function isItemsRound(round: unknown): round is MinigameItemsRound {
  return (
    !!round &&
    typeof round === "object" &&
    !Array.isArray(round) &&
    Array.isArray((round as { items?: unknown }).items)
  );
}

function isItem(item: unknown): item is MinigameItem {
  if (!item || typeof item !== "object") return false;
  const label = (item as { label?: unknown }).label;
  return typeof label === "string" || (!!label && typeof label === "object");
}

/**
 * Every round this player can render, in one shape. List rounds are only
 * playable when the rule is known; items rounds are shuffled (deterministically,
 * per game and round) because a generator may list the right items first.
 */
export function playableRounds(game: Minigame): PlayRound[] {
  const rule = RULES[game.rule?.fn ?? ""];
  const rounds: PlayRound[] = [];
  (game.rounds ?? []).forEach((round, index) => {
    if (isItemsRound(round)) {
      const items = round.items
        .filter(isItem)
        .map((item) => ({ label: item.label, correct: item.correct === true }));
      if (items.length) {
        rounds.push({ prompt: round.prompt, items: seededShuffle(items, `${game.id}:${index}`) });
      }
    } else if (Array.isArray(round) && rule) {
      rounds.push({
        items: round.map((value) => ({ label: String(value), correct: rule(Number(value)) })),
      });
    }
  });
  return rounds;
}

/* -------------------------------------------------------------------------- */
/* Game state                                                                 */
/* -------------------------------------------------------------------------- */

interface GameState {
  phase: "ready" | "playing" | "done";
  round: number;
  /** Slots tapped in the current round. */
  caught: number[];
  wrong: number[];
  score: number;
  secondsLeft: number;
}

/**
 * Every action names the round it was meant for, so a timer that fires after
 * the round already moved on (the "cleared" pause racing the countdown) is a
 * no-op instead of skipping a round.
 */
type GameAction =
  | { type: "start" }
  | { type: "tap"; round: number; slot: number; correct: boolean; points: number }
  | { type: "tick"; round: number }
  | { type: "advance"; round: number; totalRounds: number; seconds: number };

function gameReducer(state: GameState, action: GameAction): GameState {
  switch (action.type) {
    case "start":
      return state.phase === "ready" ? { ...state, phase: "playing" } : state;
    case "tap":
      if (
        state.phase !== "playing" ||
        action.round !== state.round ||
        state.caught.includes(action.slot) ||
        state.wrong.includes(action.slot)
      ) {
        return state;
      }
      return action.correct
        ? { ...state, caught: [...state.caught, action.slot], score: state.score + action.points }
        : { ...state, wrong: [...state.wrong, action.slot] };
    case "tick":
      if (state.phase !== "playing" || action.round !== state.round) return state;
      return { ...state, secondsLeft: state.secondsLeft - 1 };
    case "advance":
      if (state.phase !== "playing" || action.round !== state.round) return state;
      if (state.round + 1 >= action.totalRounds) {
        return { ...state, phase: "done", caught: [], wrong: [] };
      }
      return {
        ...state,
        round: state.round + 1,
        caught: [],
        wrong: [],
        secondsLeft: action.seconds,
      };
    default:
      return state;
  }
}

/* -------------------------------------------------------------------------- */

export function MinigameView({
  game,
  target,
  home,
  bilingual,
  active = true,
  onFinished,
  onTap,
  className,
  result,
  onRound,
  onPhase,
}: MinigameViewProps) {
  const t = useTranslations("Story");
  const rounds = useMemo(() => playableRounds(game), [game]);
  const hasItemsRounds = useMemo(() => (game.rounds ?? []).some(isItemsRound), [game.rounds]);
  const seconds =
    game.timer_s && game.timer_s > 0
      ? game.timer_s
      : hasItemsRounds
        ? DEFAULT_TIMER_ITEMS_S
        : DEFAULT_TIMER_LIST_S;
  // Same coercion as the validator's max_points: a missing or zero
  // per_correct counts as 1.
  const perCorrect = Number(game.points?.per_correct) || 1;

  const [state, dispatch] = useReducer(gameReducer, {
    phase: result === undefined ? "ready" : "done",
    round: 0,
    caught: [],
    wrong: [],
    score: result ?? 0,
    secondsLeft: seconds,
  });
  const targetsRef = useRef<HTMLUListElement | null>(null);
  const roundRef = useRef<HTMLDivElement | null>(null);
  const { phase, round, caught, wrong, score, secondsLeft } = state;
  const current = rounds[round];
  const correctSlots = useMemo(
    () =>
      (current?.items ?? []).flatMap((item, slot) => (item.correct ? [slot] : [])),
    [current],
  );

  // Countdown for the active round; it stands still while out of sight.
  useEffect(() => {
    if (phase !== "playing" || !active) return;
    const timer = setTimeout(() => {
      if (secondsLeft <= 1) {
        dispatch({ type: "advance", round, totalRounds: rounds.length, seconds });
      } else {
        dispatch({ type: "tick", round });
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [phase, active, round, secondsLeft, rounds.length, seconds]);

  // A round is cleared once every right item has been tapped.
  useEffect(() => {
    if (phase !== "playing" || correctSlots.length === 0) return;
    if (!correctSlots.every((slot) => caught.includes(slot))) return;
    const timer = setTimeout(
      () => dispatch({ type: "advance", round, totalRounds: rounds.length, seconds }),
      CLEARED_ROUND_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [phase, round, caught, correctSlots, rounds.length, seconds]);

  // Report the result exactly once. The parent passes a fresh callback on
  // every render, so it is read through a ref rather than listed as a
  // dependency — otherwise each re-render after the game would report (and
  // award the points) again.
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);
  // A game shown again has been reported already.
  const reportedRef = useRef(result !== undefined);
  useEffect(() => {
    if (phase !== "done" || reportedRef.current) return;
    reportedRef.current = true;
    onFinishedRef.current({ gameId: game.id, points: score });
  }, [phase, game.id, score]);
  const onTapRef = useRef(onTap);
  useEffect(() => {
    onTapRef.current = onTap;
  }, [onTap]);

  // Every round in view, once it is on screen.
  const onRoundRef = useRef(onRound);
  useEffect(() => {
    onRoundRef.current = onRound;
  }, [onRound]);
  useEffect(() => {
    if (phase !== "playing" || !targetsRef.current || !roundRef.current) return;
    const targets = targetsRef.current;
    const roundBox = roundRef.current;
    const frame = requestAnimationFrame(() => onRoundRef.current?.(roundBox, targets));
    return () => cancelAnimationFrame(frame);
  }, [phase, round]);

  // The host learns when a game is running (Previous waits for its end).
  const onPhaseRef = useRef(onPhase);
  useEffect(() => {
    onPhaseRef.current = onPhase;
  }, [onPhase]);
  useEffect(() => {
    onPhaseRef.current?.(phase);
  }, [phase]);

  // Keys 1-6 mirror the touch targets (A.9), only while the game is in sight
  // and the key is not meant for something else.
  useEffect(() => {
    if (phase !== "playing" || !current || !active) return;
    const onKey = (event: KeyboardEvent) => {
      if (isForeignKeyPress(event)) return;
      const slot = Number(event.key) - 1;
      if (!Number.isInteger(slot) || slot < 0 || slot >= KEYED_SLOTS) return;
      const item = current.items[slot];
      if (!item) return;
      onTapRef.current?.(item.correct);
      dispatch({ type: "tap", round, slot, correct: item.correct, points: perCorrect });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, active, round, current, perCorrect]);

  if (rounds.length === 0) {
    return (
      <section className="my-5 rounded-xl border border-dashed border-amber-400 bg-amber-50 p-4">
        <p className="font-semibold text-amber-800">{text(game.title, target, home)}</p>
        <p className="mt-1 text-sm text-amber-700">
          {t("minigameUnavailable", { engine: game.rule?.fn || game.engine })}
        </p>
        <button
          type="button"
          onClick={() => {
            if (reportedRef.current) return;
            reportedRef.current = true;
            onFinished({ gameId: game.id, points: 0 });
          }}
          className="mt-3 min-h-11 rounded-lg border border-amber-500 px-4 font-semibold text-amber-800"
        >
          {t("skipForNow")}
        </button>
      </section>
    );
  }

  const label = (value: TextObject | string, lang: string, fallback: string) =>
    typeof value === "string" ? value : text(value, lang, fallback);
  // Short labels (numbers, symbols) read best as a 3-wide grid of big tiles;
  // phrases need the width.
  const compact = (current?.items ?? []).every((item) => label(item.label, target, home).length <= 4);
  const caughtWord = game.engine === "pop" ? t("popped") : t("caught");

  return (
    <section className={className ?? "my-5 rounded-xl border-2 border-amber-300 bg-amber-50/60 p-4"}>
      <h3 className="font-bold text-gray-900">{text(game.title, target, home)}</h3>
      <p className="mt-1 text-sm text-gray-700">{text(game.instruction, target, home)}</p>
      {bilingual && text(game.instruction, home, target) !== text(game.instruction, target, home) ? (
        <p className="mt-1 text-sm italic text-gray-500" lang={home}>
          {text(game.instruction, home, target)}
        </p>
      ) : null}

      {phase === "ready" ? (
        <button
          type="button"
          onClick={() => dispatch({ type: "start" })}
          className="mt-3 min-h-11 rounded-lg bg-amber-500 px-5 font-semibold text-white hover:bg-amber-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600"
        >
          {t("start")}
        </button>
      ) : null}

      {phase === "playing" && current ? (
        <div ref={roundRef}>
          <div className="mt-3 flex items-center justify-between text-sm font-semibold text-gray-700">
            <span>{t("round", { current: round + 1, total: rounds.length })}</span>
            <span aria-live="polite">{t("secondsLeft", { seconds: secondsLeft })}</span>
          </div>

          {current.prompt ? (
            <div className="mt-3">
              <p className="font-semibold text-gray-900">{text(current.prompt, target, home)}</p>
              {bilingual && text(current.prompt, home, target) !== text(current.prompt, target, home) ? (
                <p className="mt-1 text-sm italic text-gray-500" lang={home}>
                  {text(current.prompt, home, target)}
                </p>
              ) : null}
            </div>
          ) : null}

          <ul
            ref={targetsRef}
            className={`mt-3 grid gap-2 ${compact ? "grid-cols-3" : "grid-cols-1 sm:grid-cols-2"}`}
          >
            {current.items.map((item, slot) => {
              const isCaught = caught.includes(slot);
              const isWrong = wrong.includes(slot);
              const primary = label(item.label, target, home);
              const secondary = label(item.label, home, target);
              const status = isCaught ? `, ${caughtWord}` : isWrong ? `, ${t("notThisOne")}` : "";
              return (
                <li key={`${round}-${slot}`}>
                  <button
                    type="button"
                    onClick={() => {
                      onTap?.(item.correct);
                      dispatch({ type: "tap", round, slot, correct: item.correct, points: perCorrect });
                    }}
                    disabled={isCaught || isWrong}
                    aria-label={`${primary}${status}`}
                    className={`flex w-full items-center gap-3 rounded-xl border-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600 ${
                      compact
                        ? "min-h-16 flex-col justify-center gap-0 text-xl font-bold"
                        : "min-h-14 px-3 py-2 text-left font-semibold"
                    } ${
                      isCaught
                        ? "border-green-600 bg-green-100 text-green-800"
                        : isWrong
                          ? "border-red-400 bg-red-50 text-red-400 line-through"
                          : "border-amber-400 bg-white text-gray-900 hover:bg-amber-100"
                    }`}
                  >
                    {compact ? (
                      <>
                        {primary}
                        {slot < KEYED_SLOTS ? (
                          <span className="block text-[10px] font-normal text-gray-400" aria-hidden="true">
                            {slot + 1}
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <>
                        {slot < KEYED_SLOTS ? (
                          <span
                            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current text-xs font-normal opacity-60"
                            aria-hidden="true"
                          >
                            {slot + 1}
                          </span>
                        ) : null}
                        <span className="min-w-0">
                          <span className="block">{primary}</span>
                          {bilingual && secondary !== primary ? (
                            <span className="block text-sm font-normal italic opacity-70" lang={home}>
                              {secondary}
                            </span>
                          ) : null}
                        </span>
                      </>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>

          {wrong.length > 0 && game.hint_after_wrong ? (
            <p
              className="mt-3 rounded-lg border border-amber-300 bg-white p-2 text-sm text-amber-900"
              role="status"
            >
              {text(game.hint_after_wrong, target, home)}
            </p>
          ) : null}
        </div>
      ) : null}

      {phase === "done" ? (
        <p className="mt-3 font-semibold text-green-700">{t("gameOver", { points: score })}</p>
      ) : null}
    </section>
  );
}
