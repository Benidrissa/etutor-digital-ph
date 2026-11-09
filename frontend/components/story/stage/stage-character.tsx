/**
 * One cast member on the stage: standing on the ground line at their slot,
 * walking in (a slide with small hops) when they arrive, breathing gently,
 * bobbing while they speak, jumping for joy, shaking off a wrong answer, and
 * blinking now and then.
 *
 * The picture is the course's generated art for the pose when it exists
 * (and loads); otherwise the drawn placeholder. The picture is never
 * remounted: a gesture is replayed with the Web Animations API on a wrapper,
 * and a new pose's picture replaces the old one only once it has loaded, so
 * on a slow link the speaker never blinks out of the scene.
 */

import { memo, useEffect, useRef, useState, type CSSProperties } from "react";

import { FIGURE_HEIGHT, GROUND, type Pose, type StageActor } from "./cast";
import { PlaceholderFigure } from "./placeholder-figure";
import styles from "./stage.module.css";

export type Gesture = "speak" | "jump" | "shake" | null;

interface StageCharacterProps {
  actor: StageActor;
  /** Slot, as a % of the stage width. */
  x: number;
  pose: Pose;
  artUrl?: string;
  gesture: Gesture;
  /** Changes whenever the gesture should play again (a new line, a new answer). */
  gestureKey: string;
  /** How many bobs (and mouth flaps) the line lasts. */
  beats: number;
  /** Seconds before walking in, so a group arrives one by one. */
  enterDelay: number;
  /** Shows a "…" over the head on phones, where the words sit under the stage. */
  speaking: boolean;
  /** No gestures and no blinking (reduced motion, or the stage is paused). */
  still: boolean;
}

const GESTURES: Record<Exclude<Gesture, null>, { frames: Keyframe[]; duration: number }> = {
  speak: {
    frames: [
      { transform: "translateY(0) rotate(0)" },
      { transform: "translateY(-3%) rotate(-1deg)", offset: 0.3 },
      { transform: "translateY(-1%) rotate(1deg)", offset: 0.7 },
      { transform: "translateY(0) rotate(0)" },
    ],
    duration: 420,
  },
  jump: {
    frames: [
      { transform: "translateY(0)" },
      { transform: "translateY(-16%)", offset: 0.35 },
      { transform: "translateY(-16%)", offset: 0.55 },
      { transform: "translateY(0)" },
    ],
    duration: 600,
  },
  shake: {
    frames: [
      { transform: "translateX(0)" },
      { transform: "translateX(-4%)", offset: 0.25 },
      { transform: "translateX(4%)", offset: 0.75 },
      { transform: "translateX(0)" },
    ],
    duration: 450,
  },
};

function StageCharacterView({
  actor,
  x,
  pose,
  artUrl,
  gesture,
  gestureKey,
  beats,
  enterDelay,
  speaking,
  still,
}: StageCharacterProps) {
  const gestureRef = useRef<HTMLDivElement | null>(null);
  const faceRef = useRef<HTMLDivElement | null>(null);
  // The picture on screen, and pictures that failed to load.
  const [shown, setShown] = useState<string | null>(null);
  const [failed, setFailed] = useState<ReadonlySet<string>>(() => new Set());

  // Load a new pose's picture off screen; swap it in once it is there.
  useEffect(() => {
    if (!artUrl || artUrl === shown || failed.has(artUrl) || typeof Image === "undefined") return;
    let cancelled = false;
    const image = new Image();
    image.onload = () => {
      if (!cancelled) setShown(artUrl);
    };
    image.onerror = () => {
      if (!cancelled) setFailed((previous) => new Set(previous).add(artUrl));
    };
    image.src = artUrl;
    return () => {
      cancelled = true;
    };
  }, [artUrl, shown, failed]);

  // Replay the gesture on its wrapper, without touching the picture.
  useEffect(() => {
    const element = gestureRef.current;
    if (!element || !gesture || still || typeof element.animate !== "function") return;
    const { frames, duration } = GESTURES[gesture];
    const iterations = gesture === "speak" ? Math.max(1, beats) : gesture === "jump" ? 3 : 1;
    const animation = element.animate(frames, { duration, iterations, easing: "ease-in-out" });
    return () => animation.cancel();
  }, [gesture, gestureKey, beats, still]);

  // A blink every few seconds: a class set for a moment, nothing in between.
  useEffect(() => {
    const element = faceRef.current;
    if (!element || still) return;
    let off: ReturnType<typeof setTimeout> | undefined;
    const every = 3200 + (actor.id.length % 5) * 450;
    const timer = setInterval(() => {
      element.classList.add(styles.blinking);
      off = setTimeout(() => element.classList.remove(styles.blinking), 150);
    }, every);
    return () => {
      clearInterval(timer);
      if (off) clearTimeout(off);
      element.classList.remove(styles.blinking);
    };
  }, [actor.id, still]);

  // Until the first picture has loaded, show the one asked for (it fills in
  // as it arrives); after that, the last good picture until the next is in.
  const usable = artUrl && !failed.has(artUrl) ? artUrl : null;
  const picture = shown ?? usable;
  const fromLeft = x < 50;

  return (
    <div
      className={`${styles.actor} absolute`}
      style={{
        left: `${x}%`,
        bottom: `${GROUND}%`,
        height: `${FIGURE_HEIGHT[actor.figure]}%`,
        transform: "translateX(-50%)",
        zIndex: actor.isTutor ? 3 : 2,
      }}
      data-actor={actor.id}
      data-pose={pose}
    >
      <div
        className={`${styles.walkIn} h-full`}
        style={{ "--walk-from": fromLeft ? "-320%" : "320%", animationDelay: `${enterDelay}s` } as CSSProperties}
      >
        <div className={`${styles.walkHop} h-full`} style={{ animationDelay: `${enterDelay}s` }}>
          <div ref={gestureRef} className="h-full">
            <div ref={faceRef} className={`${styles.breathe} flex h-full items-end justify-center`}>
              {picture ? (
                // eslint-disable-next-line @next/next/no-img-element -- generated art from the story API, sized by the stage
                <img
                  src={picture}
                  alt=""
                  aria-hidden="true"
                  className="h-full w-auto max-w-none select-none object-contain object-bottom drop-shadow-[0_4px_0_rgba(0,0,0,0.12)]"
                  onLoad={() => setShown((current) => current ?? picture)}
                  onError={() => setFailed((previous) => new Set(previous).add(picture))}
                  draggable={false}
                />
              ) : (
                <PlaceholderFigure
                  actor={actor}
                  pose={pose}
                  talkBeats={gesture === "speak" && !still ? Math.round((beats * 0.42) / 0.26) : 0}
                  talkKey={gestureKey}
                />
              )}
            </div>
          </div>
        </div>
      </div>
      {speaking ? (
        <span
          aria-hidden="true"
          className={`${styles.narrowOnly} ${styles.dots} absolute -top-2 left-1/2 flex -translate-x-1/2 -translate-y-full gap-1 rounded-full border-2 border-[#1d2b4f] bg-white px-2 py-1`}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-[#1d2b4f]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#1d2b4f]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#1d2b4f]" />
        </span>
      ) : null}
    </div>
  );
}

export const StageCharacter = memo(StageCharacterView);

/** Pictures asked for already: each is fetched at most once per page. */
const preloaded = new Set<string>();

/**
 * Warm the cache with the poses of the cast now on stage — and only them: a
 * whole story's art is too much for a 3G link.
 */
export function preloadPoses(urls: Iterable<string | undefined>): void {
  if (typeof Image === "undefined") return;
  for (const url of urls) {
    if (!url || preloaded.has(url)) continue;
    preloaded.add(url);
    const image = new Image();
    image.decoding = "async";
    image.src = url;
  }
}
