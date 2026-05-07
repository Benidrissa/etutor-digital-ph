// Per-attempt shuffle for quiz answer options.
//
// Claude's structured output places the correct answer at index 1 (option B)
// roughly 99% of the time, and the generated quiz JSON is permanently cached
// in `generated_content`, so every learner sees the same biased order.
// Shuffling on the client per attempt fixes the bias for both existing and
// future quizzes without touching backend storage or grading.
//
// Convention: a `displayOrder` is a permutation of [0..n-1] where
// `displayOrder[displayIdx] = originalIdx`. Renderers iterate display indices,
// click handlers translate to original indices before storing them, so the
// rest of the pipeline (server grading, offline scoring, results UI) keeps
// operating in the original index space.

export function buildDisplayOrder(
  n: number,
  rng: () => number = Math.random,
): number[] {
  const order = Array.from({ length: n }, (_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}

export function buildQuizDisplayOrders(
  questions: ReadonlyArray<{ options: ReadonlyArray<unknown> }>,
  rng: () => number = Math.random,
): number[][] {
  return questions.map((q) => buildDisplayOrder(q.options.length, rng));
}

export function displayedOptions<T>(
  question: { options: ReadonlyArray<T> },
  order: ReadonlyArray<number>,
): T[] {
  return order.map((i) => question.options[i]);
}

export function displayToOriginal(
  order: ReadonlyArray<number>,
  displayIdx: number,
): number {
  return order[displayIdx];
}

export function originalToDisplay(
  order: ReadonlyArray<number>,
  originalIdx: number,
): number {
  return order.indexOf(originalIdx);
}

export function isValidPermutation(value: unknown, n: number): value is number[] {
  if (!Array.isArray(value) || value.length !== n) return false;
  const seen = new Set<number>();
  for (const v of value) {
    if (!Number.isInteger(v) || v < 0 || v >= n) return false;
    if (seen.has(v)) return false;
    seen.add(v);
  }
  return true;
}
