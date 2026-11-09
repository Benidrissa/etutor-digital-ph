/**
 * One cast member on the stage: standing on the ground line at their slot,
 * walking in (a slide with small hops) when they arrive, breathing gently,
 * bobbing while they speak, jumping for joy, shaking off a wrong answer.
 *
 * The picture is the course's generated art for the pose when it exists
 * (and loads); otherwise the drawn placeholder.
 */

import { memo, useState, type CSSProperties } from "react";

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
  /** Changes on every new line, so the speaking bob starts over. */
  gestureKey: string;
  /** How many bobs (and mouth flaps) the line lasts. */
  beats: number;
  /** Seconds before walking in, so a group arrives one by one. */
  enterDelay: number;
  /** Shows a "…" over the head on phones, where the words sit under the stage. */
  speaking: boolean;
}

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
}: StageCharacterProps) {
  const [failed, setFailed] = useState<string | null>(null);
  const useArt = !!artUrl && failed !== artUrl;
  const fromLeft = x < 50;
  const gestureClass =
    gesture === "speak" ? styles.bob : gesture === "jump" ? styles.jump : gesture === "shake" ? styles.shake : "";

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
          <div
            key={gestureKey}
            className={`h-full ${gestureClass}`}
            style={{ "--bob-count": beats } as CSSProperties}
          >
            <div className={`${styles.breathe} flex h-full items-end justify-center`}>
              {useArt ? (
                // eslint-disable-next-line @next/next/no-img-element -- generated art from the story API, sized by the stage
                <img
                  src={artUrl}
                  alt=""
                  aria-hidden="true"
                  className="h-full w-auto max-w-none select-none object-contain object-bottom drop-shadow-[0_4px_0_rgba(0,0,0,0.12)]"
                  onError={() => setFailed(artUrl ?? null)}
                  draggable={false}
                />
              ) : (
                <PlaceholderFigure actor={actor} pose={pose} talkBeats={gesture === "speak" ? beats : 0} />
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
