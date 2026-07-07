/**
 * Country-fallback self-heal decision (#2581).
 *
 * When a lesson is served as another country's fallback, the client polls the
 * lesson endpoint for the learner's own-country version (generated in the
 * background) and swaps it in once ready. A re-fetch is "healed" only when it
 * returns a real lesson (not a 202 `generating` placeholder) that is no longer
 * a country fallback.
 */
export interface SelfHealCandidate {
  status?: string;
  country_fallback?: boolean;
}

export function isHealedLessonResponse(res: SelfHealCandidate | null | undefined): boolean {
  if (!res) return false;
  const stillGenerating = res.status === 'generating';
  return !stillGenerating && !res.country_fallback;
}
