import { describe, expect, it } from 'vitest';
import { isHealedLessonResponse } from './country-selfheal';

describe('isHealedLessonResponse', () => {
  it('treats a still-fallback lesson as not healed (keep polling)', () => {
    expect(isHealedLessonResponse({ country_fallback: true })).toBe(false);
  });

  it('treats a 202 generating placeholder as not healed (keep polling)', () => {
    expect(isHealedLessonResponse({ status: 'generating' })).toBe(false);
  });

  it('treats an own-country lesson as healed (swap in, stop polling)', () => {
    expect(isHealedLessonResponse({ country_fallback: false })).toBe(true);
    expect(isHealedLessonResponse({})).toBe(true);
  });

  it('is not fooled by a generating response that lacks country_fallback', () => {
    // Would be a bug to swap a placeholder in just because country_fallback is absent.
    expect(isHealedLessonResponse({ status: 'generating', country_fallback: undefined })).toBe(
      false,
    );
  });

  it('returns false for nullish input', () => {
    expect(isHealedLessonResponse(null)).toBe(false);
    expect(isHealedLessonResponse(undefined)).toBe(false);
  });
});
