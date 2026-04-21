'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import {
  Play,
  Pause,
  Download,
  Loader2,
  Music,
  Video as VideoIcon,
  AlertCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getModuleMedia, generateModuleMedia } from '@/lib/api';
import type { ModuleMediaResponse, MediaStatus } from '@/lib/api';

const POLL_INTERVAL_MS = 4000;
const MAX_POLL_ATTEMPTS = 60;
// Video generation on HeyGen takes ~10 min P50; the poller sweeps
// every 60s on the backend so we can afford a far longer UI poll
// window than the audio TTS path (which finishes in seconds).
const VIDEO_MAX_POLL_ATTEMPTS = 300; // ~20 minutes at 4s/tick

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

type RowStatus = MediaStatus | 'loading' | 'error';

export function ModuleMediaPlayer({ moduleId, language }: ModuleMediaPlayerProps) {
  const t = useTranslations('ModuleMediaPlayer');

  const [audioMedia, setAudioMedia] = useState<ModuleMediaResponse | null>(null);
  const [audioStatus, setAudioStatus] = useState<RowStatus>('loading');
  const [videoMedia, setVideoMedia] = useState<ModuleMediaResponse | null>(null);
  const [videoStatus, setVideoStatus] = useState<RowStatus>('loading');
  const [isAdmin, setIsAdmin] = useState(false);
  const [isGeneratingAudio, setIsGeneratingAudio] = useState(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [videoError, setVideoError] = useState(false);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);
  const audioPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const videoPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
        setAudioStatus(audio.status);
      } else {
        setAudioMedia(null);
        setAudioStatus('pending');
      }
      const video = items.find(
        (m) => m.media_type === 'video' && m.language === language
      );
      if (video) {
        setVideoMedia(video);
        setVideoStatus(video.status);
      } else {
        setVideoMedia(null);
        setVideoStatus('pending');
      }
    } catch {
      setAudioStatus('error');
      setVideoStatus('error');
    }
  }, [moduleId, language]);

  const startPolling = useCallback(
    (mediaId: string, kind: 'audio' | 'video') => {
      let attempts = 0;
      const cap = kind === 'video' ? VIDEO_MAX_POLL_ATTEMPTS : MAX_POLL_ATTEMPTS;
      const timerRef = kind === 'video' ? videoPollRef : audioPollRef;
      const setMedia = kind === 'video' ? setVideoMedia : setAudioMedia;
      const setStatus = kind === 'video' ? setVideoStatus : setAudioStatus;
      const setGenerating =
        kind === 'video' ? setIsGeneratingVideo : setIsGeneratingAudio;

      const tick = async () => {
        if (attempts >= cap) {
          setStatus('failed');
          setGenerating(false);
          return;
        }
        attempts++;
        try {
          const items = await getModuleMedia(moduleId);
          const found = items.find((m) => m.id === mediaId);
          if (found) {
            setMedia(found);
            setStatus(found.status);
            if (found.status === 'ready' || found.status === 'failed') {
              setGenerating(false);
              return;
            }
          }
        } catch {
          // keep polling
        }
        timerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
      };

      timerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    },
    [moduleId]
  );

  useEffect(() => {
    fetchMedia();
    return () => {
      if (audioPollRef.current) clearTimeout(audioPollRef.current);
      if (videoPollRef.current) clearTimeout(videoPollRef.current);
    };
  }, [fetchMedia]);

  const handleGenerateAudio = async () => {
    setIsGeneratingAudio(true);
    setAudioError(false);
    try {
      const media = await generateModuleMedia(moduleId, 'audio', language);
      setAudioMedia(media);
      setAudioStatus(media.status);
      if (media.status !== 'ready') {
        startPolling(media.id, 'audio');
      } else {
        setIsGeneratingAudio(false);
      }
    } catch {
      setAudioError(true);
      setIsGeneratingAudio(false);
    }
  };

  const handleGenerateVideo = async () => {
    setIsGeneratingVideo(true);
    setVideoError(false);
    try {
      const media = await generateModuleMedia(moduleId, 'video', language);
      setVideoMedia(media);
      setVideoStatus(media.status);
      if (media.status !== 'ready') {
        startPolling(media.id, 'video');
      } else {
        setIsGeneratingVideo(false);
      }
    } catch {
      setVideoError(true);
      setIsGeneratingVideo(false);
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

  // Loading state shows a single shimmer — both rows share one fetch.
  if (audioStatus === 'loading' && videoStatus === 'loading') {
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

  if (audioStatus === 'error' && videoStatus === 'error') {
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
              onClick={() => {
                setAudioStatus('loading');
                setVideoStatus('loading');
                fetchMedia();
              }}
            >
              {t('retry')}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const hasAudio = audioStatus === 'ready' && audioMedia?.url;
  const isAudioGenerating =
    audioStatus === 'generating' || isGeneratingAudio;
  const hasVideo = videoStatus === 'ready' && videoMedia?.url;
  const isVideoGenerating =
    videoStatus === 'generating' || isGeneratingVideo;

  return (
    <Card className="w-full">
      <CardContent className="p-4">
        <div className="flex flex-col gap-4">
          {/* ── Audio row ─────────────────────────────────────────── */}
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
                  {isAudioGenerating
                    ? t('mediaGenerating')
                    : hasAudio
                    ? t('mediaReady')
                    : t('mediaNotAvailable')}
                </p>
              </div>

              {isAudioGenerating && (
                <Loader2
                  className="w-5 h-5 text-teal-600 animate-spin flex-shrink-0"
                  aria-hidden="true"
                />
              )}

              {isAdmin && !hasAudio && !isAudioGenerating && (
                <Button
                  variant="outline"
                  size="sm"
                  className="min-h-11 flex-shrink-0"
                  onClick={handleGenerateAudio}
                  disabled={isGeneratingAudio}
                >
                  {t('generateAudio')}
                </Button>
              )}
            </div>

            {audioError && (
              <p className="text-xs text-red-600" role="alert">
                {t('errorGenerating')}
              </p>
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

          {/* ── Video row ─────────────────────────────────────────── */}
          {(hasVideo || isVideoGenerating || isAdmin) && (
            <div className="flex flex-col gap-3 border-t border-stone-100 pt-4">
              <div className="flex items-center gap-3">
                <div
                  className="w-11 h-11 rounded-full bg-amber-50 flex items-center justify-center flex-shrink-0"
                  aria-hidden="true"
                >
                  <VideoIcon className="w-5 h-5 text-amber-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-stone-900 truncate">
                    {t('watchSummary')}
                  </p>
                  <p className="text-xs text-stone-500">
                    {isVideoGenerating
                      ? t('mediaGenerating')
                      : hasVideo
                      ? t('mediaReady')
                      : t('mediaNotAvailable')}
                  </p>
                </div>

                {isVideoGenerating && (
                  <Loader2
                    className="w-5 h-5 text-amber-600 animate-spin flex-shrink-0"
                    aria-hidden="true"
                  />
                )}

                {isAdmin && !hasVideo && !isVideoGenerating && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="min-h-11 flex-shrink-0"
                    onClick={handleGenerateVideo}
                    disabled={isGeneratingVideo}
                  >
                    {t('generateVideo')}
                  </Button>
                )}
              </div>

              {videoError && (
                <p className="text-xs text-red-600" role="alert">
                  {t('errorGenerating')}
                </p>
              )}

              {hasVideo && videoMedia?.url && (
                <video
                  controls
                  className="w-full rounded-lg bg-black"
                  src={videoMedia.url}
                  preload="metadata"
                />
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
