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
