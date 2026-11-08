/**
 * Mini-game engines for the story player (format Appendix A.9).
 *
 * `pop` is implemented: tap every target that follows the rule before the
 * timer runs out, where wrong targets are the week's traps rather than random
 * numbers. Keys 1-6 mirror the touch buttons, as A.9 requires.
 *
 * The rule is evaluated in the browser. That is deliberate: a tap cannot wait
 * for a round-trip on a 2G connection, and the backend validator has already
 * recomputed the rule for every target in every round, so the two cannot
 * disagree about which mangoes are prime.
 *
 * Engines not implemented yet say so and let the learner continue, rather than
 * blocking the story on a missing mechanic.
 */

"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";

import { text } from "@/lib/story-course/answer";
import { isPrime } from "@/lib/story-course/numbers";
import type { Minigame } from "@/lib/story-course/types";

interface MinigameViewProps {
  game: Minigame;
  target: string;
  home: string;
  bilingual: boolean;
  onFinished: (outcome: { gameId: string; points: number }) => void;
}

/** Rule predicates the player can evaluate locally. */
const RULES: Record<string, (value: number) => boolean> = {
  is_prime: isPrime,
};

export function MinigameView({
  game,
  target,
  home,
  bilingual,
  onFinished,
}: MinigameViewProps) {
  const t = useTranslations("Story");
  const rounds = useMemo(
    () => (game.rounds ?? []).filter((round): round is number[] => Array.isArray(round)),
    [game.rounds],
  );
  const ruleFn = game.rule?.fn ?? "";
  const rule = RULES[ruleFn];
  const perCorrect = game.points?.per_correct ?? 1;

  const [roundIndex, setRoundIndex] = useState(0);
  const [popped, setPopped] = useState<number[]>([]);
  const [wrong, setWrong] = useState<number[]>([]);
  const [score, setScore] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(game.timer_s ?? 20);
  const [started, setStarted] = useState(false);
  const [done, setDone] = useState(false);

  // Memoized so the `?? []` fallback does not create a fresh array on every
  // render and churn the hooks below that depend on it.
  const currentRound = useMemo(() => rounds[roundIndex] ?? [], [rounds, roundIndex]);
  const targetsInRound = useMemo(
    () => (rule ? currentRound.filter((value) => rule(value)) : []),
    [currentRound, rule],
  );

  const nextRound = useCallback(() => {
    setPopped([]);
    setWrong([]);
    setSecondsLeft(game.timer_s ?? 20);
    if (roundIndex + 1 >= rounds.length) {
      setDone(true);
      setStarted(false);
    } else {
      setRoundIndex((index) => index + 1);
    }
  }, [game.timer_s, roundIndex, rounds.length]);

  // Countdown for the active round. Both the tick and the round change happen
  // inside the timer callback, so nothing is set synchronously during render.
  useEffect(() => {
    if (!started || done) return;
    const timer = setTimeout(() => {
      if (secondsLeft <= 1) {
        nextRound();
      } else {
        setSecondsLeft((value) => value - 1);
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [started, done, secondsLeft, nextRound]);

  // Round is cleared once every correct target is popped.
  useEffect(() => {
    if (!started || done || targetsInRound.length === 0) return;
    if (targetsInRound.every((value) => popped.includes(value))) {
      const timer = setTimeout(nextRound, 600);
      return () => clearTimeout(timer);
    }
  }, [started, done, popped, targetsInRound, nextRound]);

  useEffect(() => {
    if (done) onFinished({ gameId: game.id, points: score });
  }, [done, game.id, score, onFinished]);

  const tap = useCallback(
    (value: number) => {
      if (!started || done || popped.includes(value) || wrong.includes(value)) return;
      if (rule?.(value)) {
        setPopped((prev) => [...prev, value]);
        setScore((prev) => prev + perCorrect);
      } else {
        setWrong((prev) => [...prev, value]);
      }
    },
    [started, done, popped, wrong, rule, perCorrect],
  );

  // Keys 1-6 mirror the touch buttons (A.9).
  useEffect(() => {
    if (!started || done) return;
    const onKey = (event: KeyboardEvent) => {
      const slot = Number(event.key);
      if (slot >= 1 && slot <= 6 && currentRound[slot - 1] !== undefined) {
        tap(currentRound[slot - 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [started, done, currentRound, tap]);

  if (!rule) {
    return (
      <section className="my-5 rounded-xl border border-dashed border-amber-400 bg-amber-50 p-4">
        <p className="font-semibold text-amber-800">
          {text(game.title, target, home)}
        </p>
        <p className="mt-1 text-sm text-amber-700">
          {t("minigameUnavailable", { engine: ruleFn || game.engine })}
        </p>
        <button
          type="button"
          onClick={() => onFinished({ gameId: game.id, points: 0 })}
          className="mt-3 min-h-11 rounded-lg border border-amber-500 px-4 font-semibold text-amber-800"
        >
          {t("skipForNow")}
        </button>
      </section>
    );
  }

  return (
    <section className="my-5 rounded-xl border-2 border-amber-300 bg-amber-50/60 p-4">
      <h3 className="font-bold text-gray-900">{text(game.title, target, home)}</h3>
      <p className="mt-1 text-sm text-gray-700">{text(game.instruction, target, home)}</p>
      {bilingual ? (
        <p className="mt-1 text-sm italic text-gray-500" lang={home}>
          {text(game.instruction, home, target)}
        </p>
      ) : null}

      {!started && !done ? (
        <button
          type="button"
          onClick={() => setStarted(true)}
          className="mt-3 min-h-11 rounded-lg bg-amber-500 px-5 font-semibold text-white hover:bg-amber-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600"
        >
          {t("start")}
        </button>
      ) : null}

      {started && !done ? (
        <>
          <div className="mt-3 flex items-center justify-between text-sm font-semibold text-gray-700">
            <span>{t("round", { current: roundIndex + 1, total: rounds.length })}</span>
            <span aria-live="polite">{secondsLeft}s</span>
          </div>
          <ul className="mt-3 grid grid-cols-3 gap-2">
            {currentRound.map((value, slot) => {
              const isPopped = popped.includes(value);
              const isWrong = wrong.includes(value);
              return (
                <li key={`${value}-${slot}`}>
                  <button
                    type="button"
                    onClick={() => tap(value)}
                    disabled={isPopped || isWrong}
                    aria-label={`${value}${isPopped ? `, ${t("popped")}` : ""}`}
                    className={`min-h-16 w-full rounded-xl border-2 text-xl font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-600 ${
                      isPopped
                        ? "border-green-600 bg-green-100 text-green-800"
                        : isWrong
                          ? "border-red-400 bg-red-50 text-red-400 line-through"
                          : "border-amber-400 bg-white text-gray-900 hover:bg-amber-100"
                    }`}
                  >
                    {value}
                    <span className="block text-[10px] font-normal text-gray-400">
                      {slot + 1}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {wrong.length > 0 && game.hint_after_wrong ? (
            <p className="mt-3 rounded-lg border border-amber-300 bg-white p-2 text-sm text-amber-900">
              {text(game.hint_after_wrong, target, home)}
            </p>
          ) : null}
        </>
      ) : null}

      {done ? (
        <p className="mt-3 font-semibold text-green-700">
          {t("gameOver", { points: score })}
        </p>
      ) : null}
    </section>
  );
}
