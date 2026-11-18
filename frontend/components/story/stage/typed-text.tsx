/**
 * A line typed out letter by letter, like a cartoon's speech bubble.
 *
 * The whole line is in the page from the first frame — screen readers,
 * search and tests read it at once — and only its paint is held back: while
 * typing, the full text is transparent and an `aria-hidden` copy on top of it
 * shows the letters typed so far. The typing writes to the DOM directly from
 * animation frames, so a long line costs no React render per letter.
 */

import { useImperativeHandle, useLayoutEffect, useRef, type Ref } from "react";

import styles from "./stage.module.css";

export interface TypedHandle {
  /** Shows the rest of the line at once; true when there was something left. */
  skip: () => boolean;
}

interface TypedTextProps {
  text: string;
  lang?: string;
  className?: string;
  /** False (reduced motion): the line shows at once. */
  animate: boolean;
  /** Letters per second. */
  speed?: number;
  ref?: Ref<TypedHandle>;
}

export function TypedText({ text, lang, className = "", animate, speed = 38, ref }: TypedTextProps) {
  const rootRef = useRef<HTMLParagraphElement | null>(null);
  const overlayRef = useRef<HTMLSpanElement | null>(null);
  const stopRef = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const overlay = overlayRef.current;
    if (!animate || !root || !overlay || text.length < 2) return;
    let frame = 0;
    let started: number | null = null;
    const stop = () => {
      cancelAnimationFrame(frame);
      delete root.dataset.typing;
      overlay.textContent = "";
      stopRef.current = null;
    };
    const tick = (now: number) => {
      started ??= now;
      const shown = Math.floor(((now - started) / 1000) * speed);
      if (shown >= text.length) {
        stop();
        return;
      }
      overlay.textContent = text.slice(0, shown);
      frame = requestAnimationFrame(tick);
    };
    root.dataset.typing = "";
    overlay.textContent = "";
    stopRef.current = stop;
    frame = requestAnimationFrame(tick);
    return stop;
  }, [text, animate, speed]);

  useImperativeHandle(
    ref,
    () => ({
      skip: () => {
        if (!stopRef.current) return false;
        stopRef.current();
        return true;
      },
    }),
    [],
  );

  return (
    <p ref={rootRef} className={styles.typed}>
      <span className={`${styles.typedFull} block ${className}`} lang={lang}>
        {text}
      </span>
      <span ref={overlayRef} className={`${styles.typedOverlay} ${className}`} aria-hidden="true" />
    </p>
  );
}
