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
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type Ref,
} from "react";

import { FIGURE_HEIGHT, GROUND, type StageActor } from "./cast";
import styles from "./stage.module.css";
import { TypedText, type TypedHandle } from "./typed-text";

const NAVY = "#1d2b4f";

export interface SkipHandle {
  skip: () => boolean;
}

/* ---- Speech bubble ------------------------------------------------------- */

interface BubbleProps {
  name: string;
  /** Margo is labelled as the AI she is. */
  aiLabel?: string;
  actor?: StageActor;
  /** The speaker's slot, as a % of the stage width; undefined when off stage. */
  x?: number;
  primary: string;
  primaryLang: string;
  secondary?: string;
  secondaryLang: string;
  animate: boolean;
  typedRef: Ref<TypedHandle>;
}

/** Where a bubble sits on a wide stage: beside the speaker's head. */
function bubblePlacement(actor: StageActor | undefined, x: number | undefined): CSSProperties {
  const height = actor ? FIGURE_HEIGHT[actor.figure] : 46;
  if (x === undefined) {
    return {
      "--bubble-left": "20%",
      "--bubble-width": "60%",
      "--bubble-bottom": `${GROUND + 50}%`,
      "--bubble-body-max": "calc(30cqw - 2.2rem)",
      "--tail-x": "50%",
    } as CSSProperties;
  }
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
  // The stage is 4:3, so 1% of its height is 0.75cqw.
  const room = Math.max(28, 96 - bottom);
  return {
    "--bubble-left": `${left}%`,
    "--bubble-width": `${width}%`,
    "--bubble-bottom": `${bottom}%`,
    "--bubble-body-max": `calc(${(room * 0.75).toFixed(2)}cqw - 2.2rem)`,
    // On a phone the box spans the stage, so the tail points at the speaker,
    // and the name tag moves aside to leave it room.
    "--tail-x": `${x}%`,
    "--tag-left": x < 55 ? `calc(${x}% + 18px)` : "1rem",
    "--tail-x-wide": `${tail}%`,
  } as CSSProperties;
}

export function SpeechBubble({
  name,
  aiLabel,
  actor,
  x,
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
      style={{ ...bubblePlacement(actor, x), borderColor: NAVY }}
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
      className={`${styles.nameTag} absolute -top-3.5 max-w-[70%] truncate rounded-full border-2 px-2.5 py-0.5 text-xs font-extrabold uppercase tracking-wide`}
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
}: Omit<BubbleProps, "name" | "aiLabel" | "actor" | "x">) {
  return (
    <div
      className={`${styles.panel} ${styles.caption} ${styles.rise} rounded-2xl border-[3px] border-[#ffd23f] px-4 py-3 shadow-[0_5px_0_rgba(0,0,0,0.2)]`}
      style={{ background: "rgb(29 43 79 / 0.93)" }}
      data-step-panel="narrate"
    >
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
  ref,
}: ChalkboardProps) {
  // Tapping the stage while rows are still coming shows them all.
  const startedRef = useRef(0);
  const [all, setAll] = useState(false);
  const total = rowDelays.length ? rowDelays[rowDelays.length - 1] : 0;
  useEffect(() => {
    startedRef.current = Date.now();
  }, []);
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
      className={`${styles.panel} ${styles.board} ${styles.chalk} ${styles.popIn} rounded-xl px-4 py-3 text-[#f7f4ea]`}
      data-step-panel="concept"
    >
      {title ? (
        <Heading className="text-lg font-extrabold leading-tight text-[#ffe066]">{title}</Heading>
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
                <span className="block text-sm italic text-[#cfe6d8]" lang={homeLang}>
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

interface StageCardProps {
  kind: "ask" | "game" | "photo" | "video";
  /** A banner across the top: "Question", "Mini-game". */
  banner?: string;
  bannerColor?: string;
  paper?: boolean;
  children: ReactNode;
  ref?: Ref<HTMLDivElement>;
}

export function StageCard({ kind, banner, bannerColor = "#1d6fb8", paper, children, ref }: StageCardProps) {
  return (
    <div
      ref={ref}
      className={`${styles.panel} ${styles.card} ${kind === "game" ? styles.cardWide : ""} ${styles.popIn} rounded-2xl border-[3px] shadow-[0_6px_0_rgba(29,43,79,0.25)] ${
        paper ? styles.paper : "bg-white"
      }`}
      style={{ borderColor: NAVY }}
      data-step-panel={kind}
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
