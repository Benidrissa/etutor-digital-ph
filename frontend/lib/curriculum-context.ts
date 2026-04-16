const COOKIE_NAME = 'curriculum_context';
const CHANGE_EVENT = 'curriculum-context-change';

export interface CurriculumContextValue {
  slug: string;
  orgSlug?: string;
}

export function getCurriculumContext(): CurriculumContextValue | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`)
  );
  if (!match) return null;
  const raw = decodeURIComponent(match[1]);
  // Backward compat: old cookies store a plain slug string
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.slug === 'string') return parsed;
  } catch {
    // not JSON — treat as plain slug
  }
  return { slug: raw };
}

export function setCurriculumContext(slug: string, orgSlug?: string) {
  if (typeof document === 'undefined') return;
  const value: CurriculumContextValue = { slug };
  if (orgSlug) value.orgSlug = orgSlug;
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(JSON.stringify(value))};path=/;max-age=${60 * 60 * 24 * 30};samesite=lax`;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function clearCurriculumContext() {
  if (typeof document === 'undefined') return;
  document.cookie = `${COOKIE_NAME}=;path=/;max-age=0`;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function onCurriculumContextChange(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}
