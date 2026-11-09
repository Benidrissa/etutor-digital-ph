/**
 * What the stage remembers per browser: the sound switch, and the learner's
 * choices at the start of a course's story (the friend's name, the hero's
 * look). Storage can be missing or throw (private mode, blocked site data):
 * every failure falls back to the defaults, and the choice still holds for
 * this visit.
 */

import { useSyncExternalStore } from "react";

export const SOUND_KEY = "sira.story.sound";
export const CHOICES_KEY_PREFIX = "sira.story.choices:";

export interface StoryChoices {
  friend?: string;
  variant?: string;
}

/** Sound is on unless the learner turned it off. */
export function readSoundOn(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) !== "off";
  } catch {
    return true;
  }
}

export function writeSoundOn(on: boolean): void {
  try {
    window.localStorage.setItem(SOUND_KEY, on ? "on" : "off");
  } catch {
    // Not remembered; the switch still works for this visit.
  }
}

export function readChoices(courseKey: string): StoryChoices | null {
  try {
    const raw = window.localStorage.getItem(CHOICES_KEY_PREFIX + courseKey);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const { friend, variant } = parsed as Record<string, unknown>;
    return {
      friend: typeof friend === "string" ? friend.slice(0, 40) : undefined,
      variant: typeof variant === "string" ? variant : undefined,
    };
  } catch {
    return null;
  }
}

export function writeChoices(courseKey: string, choices: StoryChoices): void {
  try {
    window.localStorage.setItem(CHOICES_KEY_PREFIX + courseKey, JSON.stringify(choices));
  } catch {
    // Asked again next time; the story goes on.
  }
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeMotion(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(REDUCED_MOTION);
  query.addEventListener?.("change", onChange);
  return () => query.removeEventListener?.("change", onChange);
}

function motionSnapshot(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION).matches
  );
}

/** True when the learner asked their system for less motion. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, motionSnapshot, () => false);
}
