/**
 * A prop on the stage (#2681): the thing a line is talking about, drawn as
 * its sticker, its photo in a polaroid frame, its emoji or its name. It pops
 * in when a line first names it and bounces (with a glow) when a line names
 * it again. When it has a picture, it is a button that opens its "look
 * closely" close-up; without one it is decoration, since the line already
 * says what it is.
 */

import { useTranslations } from "next-intl";
import { memo, useEffect, useRef, useState, type CSSProperties } from "react";

import type { Prop } from "@/lib/story-course/types";

import { EMOJI_FONTS, emojiDrawn, tokenFor, type PropSlot, type PropToken } from "./props";
import styles from "./stage.module.css";

interface StagePropProps {
  prop: Prop;
  token: PropToken;
  slot: PropSlot;
  /** The prop's name in the language of the story. */
  label: string;
  lang: string;
  entering: boolean;
  pointed: boolean;
  /** Changes on every step the prop is named in, so the bounce plays again. */
  bounceKey: string;
  /** No bounce (reduced motion, or the stage is paused). */
  still: boolean;
  /** Set when the prop has a close-up to open. */
  onOpen?: (prop: Prop, trigger: HTMLButtonElement) => void;
}

const BOUNCE: Keyframe[] = [
  { transform: "translateY(0)" },
  { transform: "translateY(-22%)", offset: 0.3 },
  { transform: "translateY(0)", offset: 0.55 },
  { transform: "translateY(-12%)", offset: 0.75 },
  { transform: "translateY(0)" },
];

function StagePropView({
  prop,
  token,
  slot,
  label,
  lang,
  entering,
  pointed,
  bounceKey,
  still,
  onOpen,
}: StagePropProps) {
  const t = useTranslations("Story");
  const bounceRef = useRef<HTMLSpanElement | null>(null);
  // A sticker or photo that cannot load (offline, a missing file) gives way
  // to the prop's emoji or name, never to nothing (#2688).
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const shown: PropToken =
    (token.kind === "sticker" || token.kind === "polaroid") && token.src === failedSrc
      ? tokenFor(prop, undefined, "ground")
      : token;

  // A prop named again bounces, without being redrawn.
  useEffect(() => {
    const element = bounceRef.current;
    if (!pointed || entering || still || !element || typeof element.animate !== "function") return;
    const animation = element.animate(BOUNCE, { duration: 520, easing: "ease-out" });
    return () => animation.cancel();
  }, [pointed, entering, still, bounceKey]);

  // Font size for an emoji or a name: a share of the stage's width (4:3).
  const fontSize = `${(slot.height * 0.75 * 0.78).toFixed(2)}cqw`;
  const tableHeight = slot.onTable ? (9 / slot.height) * 100 : 0;

  const position: CSSProperties = {
    left: `${slot.x}%`,
    bottom: `${slot.bottom}%`,
    height: `${slot.height}%`,
    zIndex: slot.z,
    transform: "translateX(-50%)",
  };
  const drawing = (
    <>
      <span
        ref={bounceRef}
        className={`${entering ? styles.propEnter : ""} flex h-full items-end justify-center`}
        aria-hidden="true"
      >
        {shown.kind === "sticker" ? (
          // eslint-disable-next-line @next/next/no-img-element -- a same-origin story sticker
          <img
            key={shown.src}
            src={shown.src}
            alt=""
            className="h-full w-auto max-w-none select-none"
            draggable={false}
            onError={() => setFailedSrc(shown.src)}
          />
        ) : shown.kind === "polaroid" ? (
          // eslint-disable-next-line @next/next/no-img-element -- a same-origin story photo, never cropped
          <img
            key={shown.src}
            src={shown.src}
            alt=""
            className={`${styles.polaroid} h-full w-auto max-w-none select-none object-contain`}
            draggable={false}
            onError={() => setFailedSrc(shown.src)}
          />
        ) : shown.kind === "emoji" && emojiDrawn(shown.emoji) ? (
          <span
            className="block leading-none"
            style={{ fontSize, fontFamily: EMOJI_FONTS, filter: "drop-shadow(0 3px 0 rgba(0,0,0,0.18))" }}
          >
            {shown.emoji}
          </span>
        ) : (
          <span
            className="mb-[6%] block max-w-[30cqw] truncate rounded-full border-2 border-[#1d2b4f] bg-[#fff8db] px-2 py-0.5 font-extrabold text-[#1d2b4f] shadow"
            style={{ fontSize: "max(11px, 2.2cqw)" }}
            lang={lang}
          >
            {label}
          </span>
        )}
      </span>
      {slot.onTable ? (
        // A small table: a top board on two legs, from the floor up to the prop.
        <svg
          aria-hidden="true"
          viewBox="0 0 100 40"
          preserveAspectRatio="none"
          className="absolute left-1/2 top-full block -translate-x-1/2 overflow-visible"
          style={{ height: `${tableHeight}%`, width: "220%" }}
        >
          <rect x="12" y="6" width="7" height="34" fill="#6d4424" stroke="#3b2418" strokeWidth="1.5" />
          <rect x="81" y="6" width="7" height="34" fill="#6d4424" stroke="#3b2418" strokeWidth="1.5" />
          <rect x="0" y="0" width="100" height="8" rx="2" fill="#9a6332" stroke="#3b2418" strokeWidth="1.5" />
        </svg>
      ) : null}
    </>
  );
  const className = `${styles.prop} ${pointed ? styles.propPointed : ""} absolute block`;
  const hooks = {
    "data-prop": prop.id,
    "data-entering": entering ? "true" : undefined,
    "data-pointed": pointed ? "true" : undefined,
  };

  if (!onOpen) {
    return (
      <span className={className} style={position} aria-hidden="true" {...hooks}>
        {drawing}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`${className} ${styles.propButton}`}
      style={position}
      aria-label={t("lookCloserAt", { name: label })}
      lang={lang}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(prop, event.currentTarget);
      }}
      {...hooks}
    >
      {drawing}
    </button>
  );
}

export const StageProp = memo(StagePropView);
