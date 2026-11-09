/**
 * Confetti over the stage and the stars of a chapter's end.
 *
 * The confetti is CSS only: each piece falls in its own full-height column
 * (so a percentage of the column is a percentage of the stage) and sways on
 * the way down. Positions come from a seeded sequence, not Math.random, so a
 * render stays pure. Under reduced motion the stylesheet hides it.
 */

import type { CSSProperties } from "react";

import styles from "./stage.module.css";

const COLORS = ["#ffd23f", "#ff595e", "#1982c4", "#8ac926", "#ff924c", "#c77dff", "#ffffff"];

interface Piece {
  left: number;
  delay: number;
  fall: number;
  size: number;
  round: boolean;
  color: string;
}

/** The pieces of one burst, from a seeded sequence. */
function piecesFor(seed: number, count: number): Piece[] {
  let state = (seed * 9301 + 49297) % 233280 || 1;
  const next = () => {
    state = (state * 9301 + 49297) % 233280;
    return state / 233280;
  };
  return Array.from({ length: count }, (_, i) => ({
    left: next() * 100,
    delay: next() * 0.6,
    fall: 1.8 + next() * 1.2,
    size: 6 + next() * 6,
    round: next() > 0.6,
    color: COLORS[i % COLORS.length],
  }));
}

export function Confetti({ seed, pieces = 42 }: { seed: number; pieces?: number }) {
  const items = piecesFor(seed, pieces);
  return (
    <div className={`${styles.confetti} pointer-events-none absolute inset-0 z-30 overflow-hidden`} aria-hidden="true">
      {items.map((item, i) => (
        <div
          key={i}
          className={`${styles.confettiFall} absolute top-0 h-full`}
          style={
            {
              left: `${item.left}%`,
              "--fall-s": `${item.fall}s`,
              "--fall-delay": `${item.delay}s`,
            } as CSSProperties
          }
        >
          <div
            className={styles.confettiSway}
            style={{
              width: item.size,
              height: item.round ? item.size : item.size * 0.45,
              background: item.color,
              borderRadius: item.round ? "50%" : 2,
              boxShadow: "0 0 0 1px rgba(29,43,79,0.25)",
            }}
          />
        </div>
      ))}
    </div>
  );
}

/** One star, filled or not, in the cartoon outline style. */
export function Star({ filled, size = 40, className, style }: {
  filled: boolean;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      viewBox="0 0 48 46"
      width={size}
      height={size}
      className={className}
      style={style}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M24,2 L30.5,16 L46,17.6 L34.4,28 L37.8,43.4 L24,35.4 L10.2,43.4 L13.6,28 L2,17.6 L17.5,16 Z"
        fill={filled ? "#ffd23f" : "#e8e4f2"}
        stroke="#1d2b4f"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      {filled ? <path d="M16,18 L21,17" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" opacity="0.8" /> : null}
    </svg>
  );
}

/** A row of `max` stars with `stars` filled, popping in one after another. */
export function StarRow({ stars, max, size = 40 }: { stars: number; max: number; size?: number }) {
  return (
    <span className="inline-flex items-end gap-1" aria-hidden="true">
      {Array.from({ length: max }, (_, i) => (
        <Star
          key={i}
          filled={i < stars}
          size={i === 1 && max === 3 ? size * 1.25 : size}
          className={styles.popIn}
          style={{ animationDelay: `${0.25 + i * 0.3}s` }}
        />
      ))}
    </span>
  );
}
