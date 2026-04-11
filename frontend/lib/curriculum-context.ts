const COOKIE_NAME = 'curriculum_context';
const CHANGE_EVENT = 'curriculum-context-change';

export function getCurriculumContext(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`)
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function setCurriculumContext(slug: string) {
  if (typeof document === 'undefined') return;
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(slug)};path=/;max-age=${60 * 60 * 24 * 30};samesite=lax`;
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
