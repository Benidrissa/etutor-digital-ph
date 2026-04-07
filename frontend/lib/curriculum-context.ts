const COOKIE_NAME = 'curriculum_context';

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
}

export function clearCurriculumContext() {
  if (typeof document === 'undefined') return;
  document.cookie = `${COOKIE_NAME}=;path=/;max-age=0`;
}
