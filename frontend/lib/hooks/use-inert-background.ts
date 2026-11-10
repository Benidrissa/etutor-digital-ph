"use client";

import { useEffect, type RefObject } from "react";

/**
 * While a modal dialog portalled to the page body is open, everything else on
 * the page is made `inert`: no clicks, no focus and nothing read out behind
 * it. When the dialog closes, only what this hook made inert is restored.
 */
export function useInertBackground(ref: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    const node = ref.current;
    if (!active || !node || typeof document === "undefined") return;
    // The body's child that holds the dialog (its portal container).
    let holder: Element = node;
    while (holder.parentElement && holder.parentElement !== document.body) holder = holder.parentElement;
    const changed: Element[] = [];
    for (const child of Array.from(document.body.children)) {
      if (child === holder || child.hasAttribute("inert") || child.tagName === "SCRIPT") continue;
      child.setAttribute("inert", "");
      changed.push(child);
    }
    return () => {
      for (const element of changed) element.removeAttribute("inert");
    };
  }, [ref, active]);
}
