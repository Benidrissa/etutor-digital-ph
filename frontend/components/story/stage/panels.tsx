/**
 * What a step puts in front of the learner: a speech bubble over the
 * speaker, a caption bar for the narrator, a chalkboard for a concept, an
 * inset panel for a picture, and a card for a question, a game or a paper
 * exercise.
 *
 * Each is one element with one place in the page. Under 576px of stage it is
 * a box under the stage (the stage stylesheet's dialogue area); from 576px it
 * floats on the stage. The text order is always the target language first
 * and the home language under it.
 */

import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type Ref,
} from "react";

import { GROUND, type StageActor } from "./cast";
import styles from "./stage.module.css";
import { TypedText, type TypedHandle } from "./typed-text";

const NAVY = "#1d2b4f";

export interface SkipHandle {
  skip: () => boolean;
}

/* ---- Speech bubble ------------------------------------------------------- */

/** Someone standing on the stage: their slot and figure height, in % of the stage. */
export interface Standing {
  x: number;
  height: number;
}

interface BubbleProps {
  name: string;
  /** Margo is labelled as the AI she is. */
  aiLabel?: string;
  actor?: StageActor;
  /** Where the speaker stands; undefined when they are not on stage. */
  speaker?: Standing;
  /** Everyone else on stage: the bubble rises above any face it would cover. */
  others: Standing[];
  primary: string;
  primaryLang: string;
  secondary?: string;
  secondaryLang: string;
  animate: boolean;
  typedRef: Ref<TypedHandle>;
}

/** A figure's width as a share of the stage width (the art is about 130 x 240, the stage 4:3). */
function figureWidth(height: number): number {
  return height * (130 / 240) * 0.75;
}

export interface BubbleBox {
  left: number;
  width: number;
  bottom: number;
  /** Where the tail sits along the bubble's bottom edge, in % of its width. */
  tail: number;
}

/**
 * Where a bubble sits on a wide stage: beside the speaker's head (above it
 * for the middle slot), and above the head of anyone else it would cover.
 *
 * Only a face counts (the middle half of a figure's width, at the top of
 * it), and only when the bubble would come down over it: a bubble that
 * merely passes over someone's shoulder, or already sits higher than their
 * head, stays where it is.
 */
export function bubbleBox(speaker: Standing | undefined, others: Standing[]): BubbleBox {
  if (!speaker) return { left: 20, width: 60, bottom: GROUND + 50, tail: 50 };
  const { x, height } = speaker;
  const width = 52;
  let left: number;
  let tail: number;
  let bottom: number;
  if (x < 38) {
    left = Math.min(x + 6, 100 - width - 2);
    tail = 9;
    bottom = GROUND + height * 0.86;
  } else if (x > 62) {
    left = Math.max(2, x - 6 - width);
    tail = 91;
    bottom = GROUND + height * 0.86;
  } else {
    left = Math.min(Math.max(2, x - width / 2), 100 - width - 2);
    tail = ((x - left) / width) * 100;
    bottom = GROUND + height + 3;
  }
  for (const other of others) {
    const headHalf = figureWidth(other.height) / 4;
    const headTop = GROUND + other.height;
    const over = other.x + headHalf > left && other.x - headHalf < left + width;
    if (over && bottom < headTop) bottom = Math.max(bottom, headTop + 3);
  }
  return { left, width, bottom, tail };
}

function bubblePlacement(speaker: Standing | undefined, others: Standing[]): CSSProperties {
  const box = bubbleBox(speaker, others);
  // The stage is 4:3, so 1% of its height is 0.75cqw.
  const room = Math.max(26, 96 - box.bottom);
  const x = speaker?.x ?? 50;
  return {
    "--bubble-left": `${box.left}%`,
    "--bubble-width": `${box.width}%`,
    "--bubble-bottom": `${box.bottom}%`,
    "--bubble-body-max": `calc(${(room * 0.75).toFixed(2)}cqw - 2.2rem)`,
    // On a phone the box spans the stage, so the tail points at the speaker,
    // and the name tag moves aside to leave it room.
    "--tail-x": `${x}%`,
    "--tag-left": x < 55 ? `calc(${x}% + 18px)` : "1rem",
    "--tail-x-wide": `${box.tail}%`,
  } as CSSProperties;
}

export function SpeechBubble({
  name,
  aiLabel,
  actor,
  speaker,
  others,
  primary,
  primaryLang,
  secondary,
  secondaryLang,
  animate,
  typedRef,
}: BubbleProps) {
  return (
    <div
      className={`${styles.panel} ${styles.bubble} ${styles.popIn} rounded-[1.4rem] border-[3px] bg-white px-4 pb-3 pt-4 shadow-[0_5px_0_rgba(29,43,79,0.25)]`}
      style={{ ...bubblePlacement(speaker, others), borderColor: NAVY }}
      data-step-panel="say"
    >
      <span className={styles.bubbleTail} aria-hidden="true" />
      <NameTag name={name} aiLabel={aiLabel} color={actor?.look.accent ?? "#ffd23f"} />
      <div className={styles.bubbleBody}>
        <TypedText
          ref={typedRef}
          text={primary}
          lang={primaryLang}
          animate={animate}
          className="text-[17px] font-medium leading-snug text-gray-900"
        />
        {secondary ? (
          <p className="mt-1 text-sm italic leading-snug text-gray-600" lang={secondaryLang}>
            {secondary}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Navy text reads better than white on this colour? Compares the WCAG
 * contrast of both: they cross at a relative luminance of about 0.23.
 */
function isLight(hex: string): boolean {
  const value = hex.replace("#", "");
  if (value.length !== 6) return true;
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(value.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.23;
}

/** The speaker's name on a tab across the bubble's top edge, in their colour. */
function NameTag({ name, aiLabel, color }: { name: string; aiLabel?: string; color: string }) {
  return (
    <p
      className={`${styles.nameTag} absolute -top-3.5 truncate rounded-full border-2 px-2.5 py-0.5 text-xs font-extrabold uppercase tracking-wide`}
      style={{ borderColor: NAVY, background: color, color: isLight(color) ? NAVY : "#ffffff" }}
    >
      {name}
      {aiLabel ? ` (${aiLabel})` : ""}
    </p>
  );
}

/* ---- Caption bar ----------------------------------------------------------- */

export function CaptionBar({
  primary,
  primaryLang,
  secondary,
  secondaryLang,
  animate,
  typedRef,
  at = "bottom",
  eyebrow,
}: Omit<BubbleProps, "name" | "aiLabel" | "actor" | "speaker" | "others"> & {
  /**
   * Where the caption sits on a wide stage: at the top when props stand in
   * front of the cast's feet, so it never hides the thing the line is about.
   * On a phone it is under the stage either way.
   */
  at?: "top" | "bottom";
  /** A small line over the caption: where we are, when the ribbon gives way. */
  eyebrow?: string;
}) {
  return (
    <div
      className={`${styles.panel} ${styles.caption} ${at === "top" ? styles.captionTop : ""} ${styles.rise} rounded-2xl border-[3px] border-[#ffd23f] px-4 py-3 shadow-[0_5px_0_rgba(0,0,0,0.2)]`}
      style={{ background: "rgb(29 43 79 / 0.93)" }}
      data-step-panel="narrate"
      data-at={at}
    >
      {eyebrow ? (
        <p className="mb-1 truncate text-xs font-extrabold uppercase tracking-wide text-[#ffd23f]" lang={primaryLang}>
          {eyebrow}
        </p>
      ) : null}
      <TypedText
        ref={typedRef}
        text={primary}
        lang={primaryLang}
        animate={animate}
        className="text-[16px] font-medium leading-snug text-white"
      />
      {secondary ? (
        <p className="mt-1 text-sm italic leading-snug text-sky-100" lang={secondaryLang}>
          {secondary}
        </p>
      ) : null}
    </div>
  );
}

/* ---- Chalkboard -------------------------------------------------------------- */

interface ChalkboardProps {
  title?: string;
  /** Concept titles sit one level under the chapter heading. */
  headingLevel: 3 | 4;
  rows: string[];
  rowsLang: string;
  /** The home-language rows, row by row; empty when not shown. */
  homeRows: string[];
  homeLang: string;
  /** Seconds each row waits for the one before it to be read. */
  rowDelays: number[];
  /**
   * Which side of a wide stage the board hangs on: away from the teacher
   * presenting it, so it never covers their face.
   */
  side: "left" | "right" | "center";
  /**
   * The board's height cap on a wide stage, in % of the stage: above the
   * head of a presenter standing in the middle. Default 82%.
   */
  maxHeight?: number;
  ref?: Ref<SkipHandle>;
}

export function Chalkboard({
  title,
  headingLevel,
  rows,
  rowsLang,
  homeRows,
  homeLang,
  rowDelays,
  side,
  maxHeight,
  ref,
}: ChalkboardProps) {
  // Tapping the stage while rows are still coming shows them all.
  const startedRef = useRef(0);
  const boardRef = useRef<HTMLElement | null>(null);
  const [all, setAll] = useState(false);
  const total = rowDelays.length ? rowDelays[rowDelays.length - 1] : 0;
  useEffect(() => {
    startedRef.current = Date.now();
  }, []);
  // A board capped above a middle presenter's head that cannot hold its rows
  // there takes its full height instead of scrolling inside: reading a
  // concept matters more than seeing the teacher's face.
  useLayoutEffect(() => {
    const board = boardRef.current;
    if (!board) return;
    board.classList.remove(styles.boardUncapped);
    if (maxHeight && board.scrollHeight > board.clientHeight + 1) board.classList.add(styles.boardUncapped);
  }, [maxHeight, rows, homeRows, title]);
  useImperativeHandle(
    ref,
    () => ({
      skip: () => {
        if (all || Date.now() - startedRef.current > total * 1000) return false;
        setAll(true);
        return true;
      },
    }),
    [all, total],
  );
  const Heading = headingLevel === 3 ? "h3" : "h4";
  return (
    <section
      ref={boardRef}
      className={`${styles.panel} ${styles.board} ${
        side === "right" ? styles.boardRight : side === "left" ? styles.boardLeft : ""
      } ${styles.chalk} ${styles.popIn} rounded-xl px-4 py-3 text-[#f7f4ea]`}
      data-step-panel="concept"
      data-side={side}
      style={maxHeight ? ({ "--board-max": `${maxHeight}%` } as CSSProperties) : undefined}
    >
      {title ? (
        <Heading className="text-lg font-extrabold leading-tight text-[#fff09a]">{title}</Heading>
      ) : null}
      <ul className="mt-2 space-y-2">
        {rows.map((row, index) => (
          <li
            key={index}
            className={`${all ? "" : styles.rise} flex gap-2 text-[15px] leading-snug`}
            style={all ? undefined : { animationDelay: `${rowDelays[index] ?? 0}s` }}
          >
            <span aria-hidden="true" className="mt-[0.45em] h-2 w-2 shrink-0 rounded-full bg-[#ffe066]" />
            <span className="min-w-0">
              <span className="block" lang={rowsLang}>
                {row}
              </span>
              {homeRows[index] && homeRows[index] !== row ? (
                <span className="block text-sm italic text-[#e2f1e8]" lang={homeLang}>
                  {homeRows[index]}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ---- Picture panel and cards --------------------------------------------------- */

export function VisualPanel({ children }: { children: ReactNode }) {
  return (
    <div
      className={`${styles.panel} ${styles.inset} ${styles.popIn} rounded-2xl border-[3px] bg-white px-3 shadow-[0_5px_0_rgba(29,43,79,0.25)]`}
      style={{ borderColor: NAVY }}
      data-step-panel="show"
    >
      {children}
    </div>
  );
}

/**
 * How long a card that asks something of the learner ignores taps after it
 * appears. The tap that brought it up (on the stage, or on a Next button a
 * taller card has just pushed down) must not land on an answer.
 */
export const CARD_ARM_MS = 450;

/** Cards the learner answers: a stray tap on them costs points. */
const ARMED_KINDS: ReadonlySet<string> = new Set(["ask", "game", "photo"]);

interface StageCardProps {
  kind: "ask" | "game" | "photo" | "video";
  /** A banner across the top: "Question", "Mini-game". */
  banner?: string;
  bannerColor?: string;
  paper?: boolean;
  /** Seen again with Previous: already answered, nothing to tap by mistake. */
  review?: boolean;
  children: ReactNode;
  ref?: Ref<HTMLDivElement>;
}

export function StageCard({ kind, banner, bannerColor = "#1d6fb8", paper, review, children, ref }: StageCardProps) {
  const needsArming = ARMED_KINDS.has(kind) && !review;
  const [armed, setArmed] = useState(!needsArming);
  useEffect(() => {
    if (!needsArming) return;
    const timer = setTimeout(() => setArmed(true), CARD_ARM_MS);
    return () => clearTimeout(timer);
  }, [needsArming]);
  return (
    <div
      ref={ref}
      className={`${styles.panel} ${styles.card} ${review ? "" : styles.popIn} rounded-2xl border-[3px] shadow-[0_6px_0_rgba(29,43,79,0.25)] ${
        paper ? styles.paper : "bg-white"
      }`}
      // Until armed, the card is shown but takes no taps or clicks. It is
      // not made inert: a screen reader announces it as it appears.
      style={{ borderColor: NAVY, pointerEvents: armed ? undefined : "none" }}
      data-step-panel={kind}
      data-armed={armed ? "true" : "false"}
    >
      {banner ? (
        <p
          className="px-4 py-1.5 text-sm font-extrabold uppercase tracking-wide text-white"
          style={{ background: bannerColor }}
        >
          {banner}
        </p>
      ) : null}
      <div className="px-3 pb-3 pt-1">{children}</div>
    </div>
  );
}
