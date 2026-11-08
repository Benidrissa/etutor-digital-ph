// SSR-safe wrapper around sessionStorage. Used by the quiz, summative, and
// case-study UIs to recover from unexpected page reloads (network blips,
// accidental refresh, browser crash). sessionStorage — not localStorage —
// because progress should survive a reload but not outlive the browser
// session, and shouldn't leak across users on a shared device.

type Persisted<S> = { v: 1; state: S };

function isBrowser(): boolean {
  return typeof window !== "undefined" && !!window.sessionStorage;
}

export function loadQuizState<S>(key: string): S | null {
  if (!isBrowser()) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Persisted<S>;
    return parsed.v === 1 ? parsed.state : null;
  } catch {
    return null;
  }
}

export function saveQuizState<S>(key: string, state: S): void {
  if (!isBrowser()) return;
  try {
    sessionStorage.setItem(key, JSON.stringify({ v: 1, state } as Persisted<S>));
  } catch {
    // Quota exceeded / Safari private mode — degrade silently to in-memory state.
  }
}

export function clearQuizState(key: string): void {
  if (!isBrowser()) return;
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Ignore: storage failures here are not actionable.
  }
}

/**
 * Storage key for an in-progress quiz or assessment attempt.
 *
 * Scoped to the revision served: regeneration replaces the questions under the
 * same quiz id, and restoring answers given to the old questions would put
 * them against the new ones. Revision 1 keeps the pre-revision key so attempts
 * in progress when revisions were introduced are not lost.
 */
export function quizAttemptStorageKey(
  prefix: string,
  quiz: { id: string; content_revision?: number },
): string {
  const revision = quiz.content_revision ?? 1;
  return revision > 1 ? `${prefix}:v1:${quiz.id}:r${revision}` : `${prefix}:v1:${quiz.id}`;
}
