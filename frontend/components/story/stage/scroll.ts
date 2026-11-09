/**
 * Bringing a step into view inside the real app shell (#2682).
 *
 * The app scrolls inside its `<main>`, under a sticky header on phones and
 * over a fixed bottom navigation, and the standalone week adds its own
 * sticky header and a fixed Next bar. Fixed guesses (scroll margins in rem)
 * were wrong on a 320px phone and on short laptop screens, so the band that
 * is really visible is measured when it is needed: the scroll container's
 * box, minus whatever sticky or fixed bar covers its top or bottom edge.
 */

interface Band {
  top: number;
  bottom: number;
  scroller: HTMLElement | null;
}

function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node && node !== document.body; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return null;
}

/** The sticky or fixed bar a point on screen belongs to, if any. */
function barAt(x: number, y: number, target: HTMLElement): HTMLElement | null {
  if (typeof document.elementFromPoint !== "function") return null;
  for (let node = document.elementFromPoint(x, y); node && node !== document.body; node = node.parentElement) {
    if (node.contains(target)) return null;
    const { position } = window.getComputedStyle(node);
    if (position === "fixed" || position === "sticky") return node as HTMLElement;
  }
  return null;
}

/** The part of the screen where `target` can be seen, between the bars. */
export function visibleBand(target: HTMLElement): Band {
  const scroller = scrollParent(target);
  const port = scroller?.getBoundingClientRect();
  let top = Math.max(0, port?.top ?? 0);
  let bottom = Math.min(window.innerHeight, port?.bottom ?? window.innerHeight);
  const box = target.getBoundingClientRect();
  const x = Math.min(window.innerWidth - 2, Math.max(2, box.left + box.width / 2));
  // Bars stacked over the bottom edge: the bottom navigation, the Next bar.
  for (let i = 0; i < 4; i += 1) {
    const bar = barAt(x, bottom - 2, target);
    const edge = bar?.getBoundingClientRect().top;
    if (edge === undefined || edge <= top || edge >= bottom) break;
    bottom = edge;
  }
  // Bars stacked over the top edge: the story's sticky header.
  for (let i = 0; i < 4; i += 1) {
    const bar = barAt(x, top + 2, target);
    const edge = bar?.getBoundingClientRect().bottom;
    if (edge === undefined || edge >= bottom || edge <= top) break;
    top = edge;
  }
  return { top, bottom, scroller };
}

/**
 * Scrolls the least needed so the stretch from `from`'s top to `to`'s bottom
 * is in view; when it is taller than the visible band, its top comes first.
 */
export function reveal(
  from: HTMLElement | null | undefined,
  options: { to?: HTMLElement | null; smooth?: boolean; gap?: number } = {},
): void {
  if (!from || typeof window === "undefined") return;
  const first = from.getBoundingClientRect();
  // Not laid out (jsdom, a hidden pane): nothing to measure.
  if (first.width === 0 && first.height === 0) return;
  const last = options.to?.getBoundingClientRect();
  const top = first.top;
  const bottom = last && (last.width || last.height) ? Math.max(first.bottom, last.bottom) : first.bottom;
  const gap = options.gap ?? 12;
  const band = visibleBand(from);
  let delta = 0;
  if (bottom - top > band.bottom - band.top - 2 * gap) delta = top - (band.top + gap);
  else if (bottom > band.bottom - gap) delta = bottom - (band.bottom - gap);
  else if (top < band.top + gap) delta = top - (band.top + gap);
  if (Math.abs(delta) < 2) return;
  const behavior: ScrollBehavior = options.smooth ? "smooth" : "auto";
  const scroller = band.scroller ?? document.scrollingElement;
  if (scroller && typeof scroller.scrollBy === "function") scroller.scrollBy({ top: delta, behavior });
}
