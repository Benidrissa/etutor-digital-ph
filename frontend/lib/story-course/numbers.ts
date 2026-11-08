/**
 * Small number helpers used to *draw* the concept widgets (A.8).
 *
 * Scope note: these exist so a visual can be built from its numbers — the
 * format's claim is that "the app draws from the numbers, so the picture is
 * always right". They are not used to mark answers. Answer correctness is
 * settled server-side by the Python engine before a week can be published
 * (see `backend/app/ai/algorithms/story_maths.py`), and duplicating that here
 * would create two implementations that could disagree in front of a learner.
 *
 * Inputs are small classroom integers, so the naive algorithms are fine.
 */

const SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹";

export function isPrime(n: number): boolean {
  if (!Number.isInteger(n) || n < 2) return false;
  if (n < 4) return true;
  if (n % 2 === 0) return false;
  for (let d = 3; d * d <= n; d += 2) {
    if (n % d === 0) return false;
  }
  return true;
}

/** Prime factorisation with repeats, ascending. */
export function primeFactors(n: number): number[] {
  if (!Number.isInteger(n) || n < 2) return [];
  const out: number[] = [];
  let value = n;
  for (const prime of [2, 3]) {
    while (value % prime === 0) {
      out.push(prime);
      value /= prime;
    }
  }
  let divisor = 5;
  let step = 2;
  while (divisor * divisor <= value) {
    while (value % divisor === 0) {
      out.push(divisor);
      value /= divisor;
    }
    divisor += step;
    step = 6 - step; // 5, 7, 11, 13, … skipping multiples of 2 and 3
  }
  if (value > 1) out.push(value);
  return out;
}

export function factorsOf(n: number): number[] {
  if (!Number.isInteger(n) || n < 1) return [];
  const small: number[] = [];
  const large: number[] = [];
  for (let d = 1; d * d <= n; d += 1) {
    if (n % d === 0) {
      small.push(d);
      const partner = n / d;
      if (partner !== d) large.push(partner);
    }
  }
  return [...small, ...large.reverse()];
}

export function hcf(a: number, b: number): number {
  let x = Math.abs(a);
  let y = Math.abs(b);
  while (y) {
    [x, y] = [y, x % y];
  }
  return x;
}

export function toSuperscript(n: number): string {
  return String(n)
    .split("")
    .map((d) => SUPERSCRIPT_DIGITS[Number(d)] ?? d)
    .join("");
}

/** Render a factorisation in index form, e.g. 360 -> "2³ × 3² × 5". */
export function indexFormOf(n: number): string {
  const primes = primeFactors(n);
  const seen: number[] = [];
  const parts: string[] = [];
  for (const prime of primes) {
    if (seen.includes(prime)) continue;
    seen.push(prime);
    const power = primes.filter((p) => p === prime).length;
    parts.push(power > 1 ? `${prime}${toSuperscript(power)}` : String(prime));
  }
  return parts.join(" × ");
}

/** The rows of a division ladder for `n`: `{ p, n }` down to 1. */
export function divisionLadder(n: number): { p: number; n: number }[] {
  const rows: { p: number; n: number }[] = [];
  let current = n;
  for (const prime of primeFactors(n)) {
    rows.push({ p: prime, n: current });
    current /= prime;
  }
  return rows;
}

export interface TreeNode {
  value: number;
  children?: [TreeNode, TreeNode];
}

/**
 * Build a binary factor tree for `n`.
 *
 * `firstSplit` lets a course file pin the opening split (e.g. 72 into 8 and 9)
 * so the drawing matches the story; otherwise the smallest prime is peeled off.
 */
export function factorTree(n: number, firstSplit?: [number, number]): TreeNode {
  if (!Number.isInteger(n) || n < 2 || isPrime(n)) return { value: n };

  let left: number;
  let right: number;
  if (firstSplit && firstSplit[0] * firstSplit[1] === n) {
    [left, right] = firstSplit;
  } else {
    left = primeFactors(n)[0];
    right = n / left;
  }
  return {
    value: n,
    children: [factorTree(left), factorTree(right)],
  };
}

/** Depth of a factor tree, for sizing the SVG. */
export function treeDepth(node: TreeNode): number {
  if (!node.children) return 1;
  return 1 + Math.max(treeDepth(node.children[0]), treeDepth(node.children[1]));
}
