'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Play, Pause, Loader2, Volume2, Gauge } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { fetchTutorMessageAudio } from '@/lib/tutor-voice-api';
import { cn } from '@/lib/utils';

interface ListenButtonProps {
  conversationId: string;
  messageIndex: number;
  className?: string;
}

type State = 'idle' | 'loading' | 'playing' | 'paused' | 'failed';

const PLAYBACK_RATES = [1, 1.25, 1.5, 1.75, 2] as const;
const PLAYBACK_RATE_STORAGE_KEY = 'tutorListenRate';

function formatRate(rate: number): string {
  // Drop trailing zeros (1 → "1", 1.5 → "1.5", 1.25 → "1.25").
  return `${rate}×`;
}

function loadInitialRate(): number {
  if (typeof window === 'undefined') return 1;
  const raw = window.localStorage.getItem(PLAYBACK_RATE_STORAGE_KEY);
  const parsed = raw ? Number(raw) : NaN;
  return (PLAYBACK_RATES as readonly number[]).includes(parsed) ? parsed : 1;
}

export function ListenButton({
  conversationId,
  messageIndex,
  className,
}: ListenButtonProps) {
  const t = useTranslations('ChatTutor');
  const locale = useLocale();
  const language = (locale === 'fr' ? 'fr' : 'en') as 'fr' | 'en';
  const [state, setState] = useState<State>('idle');
  const [playbackRate, setPlaybackRate] = useState<number>(() => loadInitialRate());
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onEnded = () => setState('idle');
    const onPause = () => setState((s) => (s === 'playing' ? 'paused' : s));
    const onPlay = () => setState('playing');
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('play', onPlay);
    return () => {
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('play', onPlay);
    };
  }, []);

  // Apply rate live to the <audio> element whenever it changes.
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  const handleClick = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (state === 'playing') {
      audio.pause();
      return;
    }
    if (state === 'paused' && audio.src) {
      void audio.play();
      return;
    }
    if (state === 'loading') return;

    setState('loading');
    const { data, status } = await fetchTutorMessageAudio(
      conversationId,
      messageIndex,
      language,
    );
    if (!data || status >= 400 || data.status !== 'ready' || !data.url) {
      setState('failed');
      return;
    }
    // Backend returns a relative proxy path (/api/v1/tutor/messages/{id}/data)
    // to avoid leaking internal MinIO hostnames (#1949). Resolve to absolute
    // same-origin URL, matching the lesson-audio pattern.
    audio.src = data.url.startsWith('/') ? `${API_BASE}${data.url}` : data.url;
    // Re-apply the current rate after src change (some browsers reset it).
    audio.playbackRate = playbackRate;
    setHasLoadedOnce(true);
    try {
      await audio.play();
    } catch {
      setState('failed');
    }
  }, [state, conversationId, messageIndex, language, playbackRate]);

  const cycleRate = useCallback(() => {
    setPlaybackRate((current) => {
      const idx = PLAYBACK_RATES.indexOf(current as (typeof PLAYBACK_RATES)[number]);
      const next = PLAYBACK_RATES[(idx + 1) % PLAYBACK_RATES.length];
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(PLAYBACK_RATE_STORAGE_KEY, String(next));
      }
      return next;
    });
  }, []);

  const label =
    state === 'playing'
      ? t('voice.pause')
      : state === 'loading'
        ? t('voice.loading')
        : state === 'failed'
          ? t('voice.audioUnavailable')
          : t('voice.listen');

  const Icon =
    state === 'playing'
      ? Pause
      : state === 'loading'
        ? Loader2
        : state === 'failed'
          ? Volume2
          : Play;

  const rateLabel = t('voice.playbackRate');

  return (
    <div className={cn('mt-2 inline-flex items-center gap-1.5', className)}>
      <button
        type="button"
        onClick={handleClick}
        disabled={state === 'failed'}
        aria-label={label}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
          'bg-current/10 hover:bg-current/20 transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
          'min-h-8',
          state === 'failed' && 'opacity-60 cursor-not-allowed',
        )}
      >
        <Icon
          className={cn('w-3.5 h-3.5', state === 'loading' && 'animate-spin')}
        />
        <span>{label}</span>
      </button>

      {hasLoadedOnce && state !== 'failed' && (
        <button
          type="button"
          onClick={cycleRate}
          aria-label={rateLabel}
          title={rateLabel}
          className={cn(
            'inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium tabular-nums',
            'bg-current/5 hover:bg-current/15 transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
            'min-h-8',
          )}
        >
          <Gauge className="w-3.5 h-3.5" />
          <span>{formatRate(playbackRate)}</span>
        </button>
      )}

      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} preload="none" />
    </div>
  );
}
