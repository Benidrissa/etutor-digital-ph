'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Play, Pause, Loader2, Volume2 } from 'lucide-react';
import { fetchTutorMessageAudio } from '@/lib/tutor-voice-api';
import { cn } from '@/lib/utils';

interface ListenButtonProps {
  conversationId: string;
  messageIndex: number;
  className?: string;
}

type State = 'idle' | 'loading' | 'playing' | 'paused' | 'failed';

export function ListenButton({
  conversationId,
  messageIndex,
  className,
}: ListenButtonProps) {
  const t = useTranslations('ChatTutor.voice');
  const locale = useLocale();
  const language = (locale === 'fr' ? 'fr' : 'en') as 'fr' | 'en';
  const [state, setState] = useState<State>('idle');
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
    audio.src = data.url;
    try {
      await audio.play();
    } catch {
      setState('failed');
    }
  }, [state, conversationId, messageIndex, language]);

  const label =
    state === 'playing'
      ? t('pause')
      : state === 'loading'
        ? t('loading')
        : state === 'failed'
          ? t('audioUnavailable')
          : t('listen');

  const Icon =
    state === 'playing'
      ? Pause
      : state === 'loading'
        ? Loader2
        : state === 'failed'
          ? Volume2
          : Play;

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={state === 'failed'}
        aria-label={label}
        className={cn(
          'mt-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
          'bg-current/10 hover:bg-current/20 transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
          'min-h-8',
          state === 'failed' && 'opacity-60 cursor-not-allowed',
          className,
        )}
      >
        <Icon
          className={cn('w-3.5 h-3.5', state === 'loading' && 'animate-spin')}
        />
        <span>{label}</span>
      </button>
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} preload="none" />
    </>
  );
}
