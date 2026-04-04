'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Play, Pause, Download, Loader2, Music, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getModuleMedia, generateModuleMedia } from '@/lib/api';
import type { ModuleMediaResponse, MediaStatus } from '@/lib/api';

const POLL_INTERVAL_MS = 4000;
const MAX_POLL_ATTEMPTS = 60;

function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64Url = token.split('.')[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

function isAdminOrExpert(): boolean {
  if (typeof window === 'undefined') return false;
  const token = localStorage.getItem('access_token');
  if (!token) return false;
  const payload = parseJwtPayload(token);
  const role = payload?.role as string | undefined;
  return role === 'admin' || role === 'expert';
}

function formatDuration(seconds: number): { minutes: string; seconds: string } {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return {
    minutes: String(m).padStart(2, '0'),
    seconds: String(s).padStart(2, '0'),
  };
}

interface ModuleMediaPlayerProps {
  moduleId: string;
  language: 'fr' | 'en';
}

export function ModuleMediaPlayer({ moduleId, language }: ModuleMediaPlayerProps) {
  const t = useTranslations('ModuleMediaPlayer');

  const [audioMedia, setAudioMedia] = useState<ModuleMediaResponse | null>(null);
  const [status, setStatus] = useState<MediaStatus | 'loading' | 'error'>('loading');
  const [isAdmin, setIsAdmin] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState(false);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setIsAdmin(isAdminOrExpert());
  }, []);

  const fetchMedia = useCallback(async () => {
    try {
      const items = await getModuleMedia(moduleId);
      const audio = items.find(
        (m) => m.media_type === 'audio' && m.language === language
      );
      if (audio) {
        setAudioMedia(audio);
        setStatus(audio.status);
        return audio;
      } else {
        setAudioMedia(null);
        setStatus('pending');
        return null;
      }
    } catch {
      setStatus('error');
      return null;
    }
  }, [moduleId, language]);

  const startPolling = useCallback(
    (mediaId: string) => {
      let attempts = 0;

      const tick = async () => {
        if (attempts >= MAX_POLL_ATTEMPTS) {
          setStatus('failed');
          setIsGenerating(false);
          return;
        }
        attempts++;

        try {
          const items = await getModuleMedia(moduleId);
          const audio = items.find((m) => m.id === mediaId);
          if (audio) {
            setAudioMedia(audio);
            setStatus(audio.status);
            if (audio.status === 'ready' || audio.status === 'failed') {
              setIsGenerating(false);
              return;
            }
          }
        } catch {
          // keep polling
        }

        pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
      };

      pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    },
    [moduleId]
  );

  useEffect(() => {
    fetchMedia();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [fetchMedia]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    setGenerateError(false);
    try {
      const media = await generateModuleMedia(moduleId, 'audio', language);
      setAudioMedia(media);
      setStatus(media.status);
      if (media.status !== 'ready') {
        startPolling(media.id);
      } else {
        setIsGenerating(false);
      }
    } catch {
      setGenerateError(true);
      setIsGenerating(false);
    }
  };

  const handlePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(() => {});
    }
  };

  const handleTimeUpdate = () => {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrentTime(audio.currentTime);
  };

  const handleLoadedMetadata = () => {
    const audio = audioRef.current;
    if (!audio) return;
    setDuration(audio.duration);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const newTime = Number(e.target.value);
    audio.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;
  const currentFmt = formatDuration(currentTime);
  const durationFmt = formatDuration(duration);

  if (status === 'loading') {
    return (
      <Card className="w-full">
        <CardContent className="p-4">
          <div className="animate-pulse flex items-center gap-3">
            <div className="w-11 h-11 rounded-full bg-stone-200 flex-shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="h-4 bg-stone-200 rounded w-1/3" />
              <div className="h-2 bg-stone-200 rounded" />
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === 'error') {
    return (
      <Card className="w-full">
        <CardContent className="p-4">
          <div className="flex items-center gap-3 text-stone-500">
            <AlertCircle className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
            <span className="text-sm">{t('errorLoading')}</span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto min-h-11 min-w-11"
              onClick={() => { setStatus('loading'); fetchMedia(); }}
            >
              {t('retry')}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const hasAudio = status === 'ready' && audioMedia?.url;
  const isCurrentlyGenerating = status === 'generating' || isGenerating;

  return (
    <Card className="w-full">
      <CardContent className="p-4">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div
              className="w-11 h-11 rounded-full bg-teal-50 flex items-center justify-center flex-shrink-0"
              aria-hidden="true"
            >
              <Music className="w-5 h-5 text-teal-600" />
            </div>

            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-stone-900 truncate">
                {t('listenToSummary')}
              </p>
              <p className="text-xs text-stone-500">
                {isCurrentlyGenerating
                  ? t('mediaGenerating')
                  : hasAudio
                  ? t('mediaReady')
                  : t('mediaNotAvailable')}
              </p>
            </div>

            {isCurrentlyGenerating && (
              <Loader2
                className="w-5 h-5 text-teal-600 animate-spin flex-shrink-0"
                aria-hidden="true"
              />
            )}

            {isAdmin && !hasAudio && !isCurrentlyGenerating && (
              <Button
                variant="outline"
                size="sm"
                className="min-h-11 flex-shrink-0"
                onClick={handleGenerate}
                disabled={isGenerating}
              >
                {t('generateAudio')}
              </Button>
            )}
          </div>

          {generateError && (
            <p className="text-xs text-red-600" role="alert">
              {t('errorGenerating')}
            </p>
          )}

          {isCurrentlyGenerating && (
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
              <span>{t('generating')}</span>
            </div>
          )}

          {hasAudio && audioMedia?.url && (
            <>
              <audio
                ref={audioRef}
                src={audioMedia.url}
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onEnded={() => setIsPlaying(false)}
                preload="metadata"
              />

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handlePlayPause}
                  className="w-11 h-11 min-w-11 min-h-11 rounded-full bg-teal-600 hover:bg-teal-700 flex items-center justify-center text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 flex-shrink-0"
                  aria-label={isPlaying ? t('pause') : t('play')}
                >
                  {isPlaying ? (
                    <Pause className="w-5 h-5" aria-hidden="true" />
                  ) : (
                    <Play className="w-5 h-5 ml-0.5" aria-hidden="true" />
                  )}
                </button>

                <div className="flex-1 flex flex-col gap-1 min-w-0">
                  <input
                    type="range"
                    min={0}
                    max={duration || 0}
                    step={0.1}
                    value={currentTime}
                    onChange={handleSeek}
                    className="w-full h-2 accent-teal-600 cursor-pointer"
                    aria-label={t('listenToSummary')}
                    style={{
                      background: `linear-gradient(to right, #0d9488 ${progressPercent}%, #e7e5e4 ${progressPercent}%)`,
                    }}
                  />
                  <div className="flex justify-between text-xs text-stone-500">
                    <span>
                      {t('duration', {
                        minutes: currentFmt.minutes,
                        seconds: currentFmt.seconds,
                      })}
                    </span>
                    <span>
                      {t('duration', {
                        minutes: durationFmt.minutes,
                        seconds: durationFmt.seconds,
                      })}
                    </span>
                  </div>
                </div>

                <a
                  href={audioMedia.url}
                  download
                  className="w-11 h-11 min-w-11 min-h-11 rounded-full border border-stone-200 flex items-center justify-center text-stone-600 hover:bg-stone-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 flex-shrink-0"
                  aria-label={t('downloadMedia')}
                >
                  <Download className="w-4 h-4" aria-hidden="true" />
                </a>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
