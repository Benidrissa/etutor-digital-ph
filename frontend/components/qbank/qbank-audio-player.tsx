'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import {
  getQBankQuestionAudio,
  type QBankAudioLanguage,
  type QBankQuestionAudioStatus,
} from '@/lib/api';

const LANGUAGES: QBankAudioLanguage[] = ['fr', 'mos', 'dyu', 'bam', 'ful'];
const STORAGE_KEY = 'qbank-audio-lang';

interface QBankAudioPlayerProps {
  questionId: string;
  /** Preferred default when nothing is in localStorage yet (e.g. bank.language). */
  defaultLanguage?: QBankAudioLanguage;
  /**
   * Pre-fetched audio URLs keyed by language. When a URL exists here
   * we mount the <audio> element directly instead of polling the
   * status endpoint — saves a round-trip per question/language switch
   * and is the fast path once pregeneration has run (#1674).
   */
  preloadedUrls?: Record<string, string>;
}

/**
 * Per-question audio player with a language picker (fr/mos/dyu/bam/ful).
 *
 * Driving-school learners who can't read rely on this — the audio is
 * the primary way they answer the question. We don't hide it behind a
 * preferences toggle: the language pills are always visible and the
 * last selection persists across questions via localStorage (#1659, #1670).
 */
export function QBankAudioPlayer({
  questionId,
  defaultLanguage,
  preloadedUrls,
}: QBankAudioPlayerProps) {
  const t = useTranslations('qbank');
  const tLang = useTranslations('qbank.audioLanguages');
  const [language, setLanguage] = useState<QBankAudioLanguage>(() => {
    if (typeof window === 'undefined') return defaultLanguage ?? 'fr';
    const saved = window.localStorage.getItem(STORAGE_KEY) as QBankAudioLanguage | null;
    if (saved && LANGUAGES.includes(saved)) return saved;
    return defaultLanguage ?? 'fr';
  });
  const [status, setStatus] = useState<QBankQuestionAudioStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  const preloadedUrl = preloadedUrls?.[language];

  useEffect(() => {
    // Fast path: test-start gave us a ready URL for this language, so
    // we derive the status in render and skip the network call entirely
    // (#1674). No setState here — the derived status below covers it.
    if (preloadedUrl) return;

    let cancelled = false;
    // Old-state resets moved into the callbacks: sync setStates inside an
    // effect body cascade re-renders and trip the no-sync-set-state lint
    // rule (#1666). The brief flicker of stale status on question/language
    // change is acceptable — it's replaced atomically when the fetch
    // resolves.
    getQBankQuestionAudio(questionId, language)
      .then((s) => {
        if (cancelled) return;
        setError(null);
        setStatus(s);
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus(null);
        setError(err instanceof Error ? err.message : 'Audio fetch failed');
      });
    return () => { cancelled = true; };
  }, [questionId, language, preloadedUrl]);

  // Derived status: preloaded URL wins over any cached fetch result so
  // the <audio> element mounts synchronously on the first render.
  const effectiveStatus: QBankQuestionAudioStatus | null = preloadedUrl
    ? {
        question_id: questionId,
        language,
        status: 'ready',
        audio_url: preloadedUrl,
        duration_seconds: null,
      }
    : status;
  const effectiveError = preloadedUrl ? null : error;

  // Persist the learner's chosen language across questions.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(STORAGE_KEY, language);
  }, [language]);

  // Stop playback when we switch language; the new audio will mount a fresh <audio>.
  useEffect(() => {
    if (audioRef.current) audioRef.current.pause();
  }, [language]);

  return (
    <div className="flex flex-col gap-1.5 sm:gap-2" aria-label={t('audio.label')}>
      <div
        role="radiogroup"
        aria-label={t('audio.languagePickerLabel')}
        className="flex flex-wrap gap-1.5 sm:gap-2"
      >
        {LANGUAGES.map((lang) => {
          const isSelected = lang === language;
          return (
            <button
              key={lang}
              type="button"
              role="radio"
              aria-checked={isSelected}
              aria-label={t('audio.pillAriaLabel', { language: tLang(lang) })}
              onClick={() => setLanguage(lang)}
              // min-h-9 on mobile keeps the pills compact so the 4-5
              // language row fits next to the image; bumps to min-h-11
              // on sm+ where there is room for WCAG touch targets.
              className={cn(
                'min-h-9 rounded-full border px-3 py-1 text-xs font-medium transition-colors sm:min-h-11 sm:px-4 sm:py-1.5 sm:text-sm',
                isSelected
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background hover:border-primary/50'
              )}
            >
              {tLang(lang)}
            </button>
          );
        })}
      </div>

      {effectiveError && (
        <p className="text-xs text-destructive" role="alert">
          {t('audio.error')}
        </p>
      )}

      {effectiveStatus?.status === 'failed' && (
        <p className="text-xs text-destructive" role="alert">{t('audio.failed')}</p>
      )}

      {effectiveStatus?.status === 'ready' && effectiveStatus.audio_url && (
        <audio
          ref={audioRef}
          src={effectiveStatus.audio_url}
          controls
          preload="auto"
          className="h-9 w-full sm:h-10"
        >
          {t('audio.unsupported')}
        </audio>
      )}

      {/* The "loading" and "notReady" states are intentionally silent on
          the test-taker to avoid eating vertical space while the learner
          is under a timer. Audio availability is communicated by whether
          the <audio> element renders at all. */}
    </div>
  );
}
