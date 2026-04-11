'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Play, Pause, Volume2, Loader2 } from 'lucide-react';
import { getLessonAudioStatus, API_BASE } from '@/lib/api';
import type { LessonAudioStatus } from '@/lib/api';

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 40;

interface LessonAudioProps {
  lessonId: string;
  language: 'fr' | 'en';
}

export function LessonAudio({ lessonId, language }: LessonAudioProps) {
  const t = useTranslations('LessonAudio');
  const [status, setStatus] = useState<LessonAudioStatus>('pending');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const poll = useCallback(async () => {
    let attempts = 0;

    const tick = async () => {
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setStatus('failed');
        return;
      }
      attempts++;

      try {
        const data = await getLessonAudioStatus(lessonId);
        setStatus(data.status);

        if (data.status === 'ready' && data.url) {
          const resolvedUrl = data.url.startsWith('/')
            ? `${API_BASE}${data.url}`
            : data.url;
          setAudioUrl(resolvedUrl);
          if (data.duration_seconds) {
            setDuration(data.duration_seconds);
          }
          return;
        }

        if (data.status === 'failed') {
          return;
        }

        setTimeout(tick, POLL_INTERVAL_MS);
      } catch {
        setTimeout(tick, POLL_INTERVAL_MS);
      }
    };

    tick();
  }, [lessonId]);

  useEffect(() => {
    poll();
  }, [poll]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => {
      if (audio.duration) {
        setProgress((audio.currentTime / audio.duration) * 100);
      }
    };
    const onLoadedMetadata = () => {
      if (audio.duration && isFinite(audio.duration)) {
        setDuration(Math.round(audio.duration));
      }
    };
    const onEnded = () => {
      setIsPlaying(false);
      setProgress(0);
    };

    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('loadedmetadata', onLoadedMetadata);
    audio.addEventListener('ended', onEnded);

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('loadedmetadata', onLoadedMetadata);
      audio.removeEventListener('ended', onEnded);
    };
  }, [audioUrl]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      audio.play();
      setIsPlaying(true);
    }
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  if (status === 'failed') {
    return null;
  }

  if (status !== 'ready' || !audioUrl) {
    return (
      <div
        className="w-full max-w-xl mx-auto my-4 rounded-lg overflow-hidden animate-pulse"
        aria-busy="true"
        aria-label={t('audioPending')}
      >
        <div className="bg-gray-100 h-14 flex items-center justify-center gap-2 rounded-lg px-4">
          <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
          <p className="text-gray-500 text-sm">{t('audioPending')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-xl mx-auto my-4">
      <div className="flex items-center gap-3 bg-teal-50 border border-teal-200 rounded-lg px-4 py-3">
        <button
          type="button"
          onClick={togglePlay}
          className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full bg-teal-600 text-white hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 min-h-11 min-w-11"
          aria-label={isPlaying ? t('pause') : t('play')}
        >
          {isPlaying ? (
            <Pause className="w-4 h-4" />
          ) : (
            <Play className="w-4 h-4 ml-0.5" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Volume2 className="w-3.5 h-3.5 text-teal-600 flex-shrink-0" />
            <span className="text-sm font-medium text-teal-800 truncate">
              {t('listenToSummary')}
            </span>
          </div>

          <div
            className="w-full h-1.5 bg-teal-200 rounded-full cursor-pointer"
            onClick={handleProgressClick}
            role="progressbar"
            aria-valuenow={Math.round(progress)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-teal-600 rounded-full transition-[width] duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {duration > 0 && (
          <span className="text-xs text-teal-600 flex-shrink-0 tabular-nums">
            {audioRef.current
              ? formatTime(audioRef.current.currentTime)
              : '0:00'}
            {' / '}
            {formatTime(duration)}
          </span>
        )}
      </div>

      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
    </div>
  );
}
