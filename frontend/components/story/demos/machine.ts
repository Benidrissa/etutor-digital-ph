import { useEffect, useState } from "react";

/** What an idea machine (#2740, #2756) is given by the player. */
export interface MachineProps {
  params: Record<string, unknown>;
  lang: "fr" | "en";
  /** The machine has been started (by its cue, or when its step appeared). */
  play: boolean;
  /** Show the end state now (a step seen again, or the learner moved on). */
  reveal?: boolean;
  /** Reduced motion: stills, advanced by the button. */
  reduced?: boolean;
}

/** The outline of a highlighted part: the colour `.propPointed` uses without motion. */
export const OUTLINE = "#ffd23f";

/**
 * The step a machine shows, 0 to `last`. Animated, it advances by itself once
 * `play` is on; with reduced motion only `next` moves it; `reveal` is the end.
 */
export function useMachineStep(last: number, { play, reveal, reduced }: Pick<MachineProps, "play" | "reveal" | "reduced">) {
  const [at, setAt] = useState(0);
  const step = reveal ? last : Math.min(at, last);
  useEffect(() => {
    if (reduced || !play || reveal || at >= last) return;
    const timer = setTimeout(() => setAt(at + 1), at === 0 ? 250 : 700);
    return () => clearTimeout(timer);
  }, [at, last, play, reveal, reduced]);
  return { step, next: () => setAt(Math.min(step + 1, last)) };
}
