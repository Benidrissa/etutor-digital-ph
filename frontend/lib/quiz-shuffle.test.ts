import { describe, it, expect } from "vitest";

import {
  buildDisplayOrder,
  buildQuizDisplayOrders,
  displayToOriginal,
  displayedOptions,
  isValidPermutation,
  originalToDisplay,
} from "./quiz-shuffle";

// Deterministic seeded RNG so reproducibility tests don't depend on Math.random.
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("buildDisplayOrder", () => {
  it("returns a permutation of [0..n-1]", () => {
    const order = buildDisplayOrder(4);
    expect(order).toHaveLength(4);
    expect([...order].sort((a, b) => a - b)).toEqual([0, 1, 2, 3]);
  });

  it("is deterministic with an injected RNG", () => {
    const a = buildDisplayOrder(4, mulberry32(42));
    const b = buildDisplayOrder(4, mulberry32(42));
    expect(a).toEqual(b);
  });

  it("handles n=1 as identity", () => {
    expect(buildDisplayOrder(1)).toEqual([0]);
  });

  it("distributes index 1 across positions roughly uniformly", () => {
    const counts = [0, 0, 0, 0];
    const N = 10_000;
    for (let i = 0; i < N; i++) {
      const order = buildDisplayOrder(4);
      counts[order.indexOf(1)]++;
    }
    // Identity permutation would put index 1 at position 1 100% of the time;
    // this guards against accidental regression to identity. Loose tolerance
    // (20–30%) makes the test deterministically pass for a real shuffle.
    for (const c of counts) {
      expect(c / N).toBeGreaterThan(0.2);
      expect(c / N).toBeLessThan(0.3);
    }
  });
});

describe("displayToOriginal / originalToDisplay", () => {
  it("are inverses across all positions", () => {
    const order = [2, 0, 3, 1];
    for (let original = 0; original < 4; original++) {
      expect(displayToOriginal(order, originalToDisplay(order, original))).toBe(
        original,
      );
    }
    for (let display = 0; display < 4; display++) {
      expect(originalToDisplay(order, displayToOriginal(order, display))).toBe(
        display,
      );
    }
  });
});

describe("displayedOptions", () => {
  it("returns options in shuffled order", () => {
    const q = { options: ["A-text", "B-text", "C-text", "D-text"] };
    expect(displayedOptions(q, [2, 0, 3, 1])).toEqual([
      "C-text",
      "A-text",
      "D-text",
      "B-text",
    ]);
  });
});

describe("buildQuizDisplayOrders", () => {
  it("returns one valid permutation per question, sized to that question", () => {
    const questions = [
      { options: ["a", "b", "c", "d"] },
      { options: ["x", "y", "z"] },
    ];
    const orders = buildQuizDisplayOrders(questions);
    expect(orders).toHaveLength(2);
    expect(isValidPermutation(orders[0], 4)).toBe(true);
    expect(isValidPermutation(orders[1], 3)).toBe(true);
  });
});

describe("isValidPermutation", () => {
  it("accepts a valid permutation", () => {
    expect(isValidPermutation([2, 0, 3, 1], 4)).toBe(true);
  });

  it("rejects duplicates", () => {
    expect(isValidPermutation([0, 1, 1, 3], 4)).toBe(false);
  });

  it("rejects wrong length", () => {
    expect(isValidPermutation([0, 1, 2], 4)).toBe(false);
  });

  it("rejects out-of-range values", () => {
    expect(isValidPermutation([0, 1, 2, 5], 4)).toBe(false);
  });

  it("rejects non-arrays", () => {
    expect(isValidPermutation(null, 4)).toBe(false);
    expect(isValidPermutation(undefined, 4)).toBe(false);
    expect(isValidPermutation("0,1,2,3", 4)).toBe(false);
  });

  it("rejects non-integer values", () => {
    expect(isValidPermutation([0, 1.5, 2, 3], 4)).toBe(false);
  });
});
