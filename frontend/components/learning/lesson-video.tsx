'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Loader2, Video as VideoIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { API_BASE, generateLessonVideo, getLessonVideoStatus } from '@/lib/api';
import type { LessonVideoStatus } from '@/lib/api';

// Video generation on HeyGen takes ~10 min P50; the backend Celery
// poller ticks every 60 s so a 20-minute UI poll window (60 × 20 s)
// is plenty.
const POLL_INTERVAL_MS = 20_000;
const MAX_POLL_ATTEMPTS = 60;

interface LessonVideoProps {
  lessonId: string;
  /** FR/EN follows the lesson language. */
  language: 'fr' | 'en';
  /**
   * Lifted whenever the "actively generating" derived state flips. Lets
   * a parent (e.g. ``LessonMediaTabs``) badge a tab trigger while the
   * HeyGen render is in flight without having to mirror the full status
   * machine.
   */
  onActivelyGeneratingChange?: (active: boolean) => void;
}

/**
 * Per-lesson HeyGen video summary row.
 *
 * Any authenticated learner or admin can click "Generate video" —
 * the backend's ``video-summary-feature-enabled`` flag is the real
 * gate. Once ready, the native ``<video controls>`` element plays
 * the HeyGen MP4 proxied through ``/api/v1/video/{id}/data`` from
 * MinIO.
 */
export function LessonVideo({
  lessonId,
  language,
  onActivelyGeneratingChange,
}: LessonVideoProps) {
  const t = useTranslations('LessonVideo');
  const [status, setStatus] = useState<LessonVideoStatus | 'loading' | 'error'>(
    'loading',
  );
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoId, setVideoId] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null until the player has fired onLoadedMetadata and we know the
  // source's natural orientation. HeyGen's Video Agent can return
  // 9:16 shorts or 16:9 landscape depending on the prompt (#1880),
  // and we want both to look intentional — portrait centered in a
  // narrow column, landscape spanning the lesson width (#1881).
  const [videoOrientation, setVideoOrientation] = useState<
    'landscape' | 'portrait' | null
  >(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  // Hold the latest callback so the lift-up effect below can read it
  // without forcing the parent to memoize.
  const onActivelyGeneratingChangeRef = useRef(onActivelyGeneratingChange);
  useEffect(() => {
    onActivelyGeneratingChangeRef.current = onActivelyGeneratingChange;
  }, [onActivelyGeneratingChange]);

  const refresh = useCallback(async () => {
    try {
      const data = await getLessonVideoStatus(lessonId);
      setStatus(data.status);
      setVideoId(data.video_id ?? null);
      if (data.status === 'ready' && data.url) {
        const resolved = data.url.startsWith('/')
          ? `${API_BASE}${data.url}`
          : data.url;
        setVideoUrl(resolved);
      } else {
        setVideoUrl(null);
      }
      return data;
    } catch {
      setStatus('error');
      setVideoId(null);
      return null;
    }
  }, [lessonId]);

  const startPolling = useCallback(() => {
    let attempts = 0;
    const tick = async () => {
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setStatus('failed');
        setIsGenerating(false);
        return;
      }
      attempts++;
      const data = await refresh();
      const s = data?.status ?? 'error';
      if (s === 'ready' || s === 'failed' || s === 'absent') {
        setIsGenerating(false);
        return;
      }
      pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    };
    pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
  }, [refresh]);

  useEffect(() => {
    // ``language`` is listed so a locale switch while the component
    // is mounted re-fetches against the correct cache row. The API
    // itself resolves language from the lesson, so this is a belt-
    // and-suspenders refresh.
    void language;
    refresh().then((data) => {
      // Only auto-resume polling when a real row exists and is in-
      // flight. Guarding on ``data.video_id`` defends against every
      // code path that surfaces a synthetic ``pending`` without an
      // actual DB row (#1824): 404 → 'absent', empty list → old
      // fallback, etc. No row → user must click Generate first.
      if (
        data?.video_id &&
        (data.status === 'generating' || data.status === 'pending')
      ) {
        setIsGenerating(true);
        startPolling();
      }
    });
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [refresh, startPolling, language]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    setError(null);
    try {
      const result = await generateLessonVideo(lessonId);
      setVideoId(result.video_id);
      if (result.status === 'ready') {
        await refresh();
        setIsGenerating(false);
      } else {
        setStatus(result.status);
        startPolling();
      }
    } catch (err: unknown) {
      const s = (err as { status?: number })?.status;
      if (s === 403) {
        setError(t('featureDisabled'));
      } else {
        setError(t('generateError'));
      }
      setIsGenerating(false);
    }
  };

  // Only show the generating UI when a row actually exists (or we
  // just clicked Generate). A synthetic ``pending`` without a row
  // has bitten us twice (#1824); require ``videoId`` as the ground
  // truth that a DB row was dispatched.
  const isActivelyGenerating =
    isGenerating ||
    (videoId !== null && (status === 'generating' || status === 'pending'));

  useEffect(() => {
    onActivelyGeneratingChangeRef.current?.(isActivelyGenerating);
  }, [isActivelyGenerating]);

  // Loading / error / pending / failed all fall through to the same
  // "no video yet" card so the learner always sees the Generate
  // button — hiding on error made the component invisible when the
  // status fetch flaked (#1802 post-deploy regression).
  if (status === 'ready' && videoUrl) {
    // Portrait sources render in a phone-shaped column (natural 9:16
    // with no pillarboxing); landscape sources span the lesson width
    // as before. We read the source's natural dimensions via
    // onLoadedMetadata rather than assuming an aspect so a future
    // 16:9 regen (see #1880) just "works" against the same player
    // without any code change.
    const playerWrapperClass =
      videoOrientation === 'portrait'
        ? 'mx-auto w-full max-w-[min(360px,100%)]'
        : 'w-full';
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm text-stone-600">
          <VideoIcon className="w-4 h-4 text-amber-600" aria-hidden="true" />
          <span>{t('watchSummary')}</span>
        </div>
        <div className={playerWrapperClass}>
          <video
            ref={videoRef}
            controls
            preload="metadata"
            className="w-full rounded-lg bg-black"
            src={videoUrl}
            onLoadedMetadata={() => {
              const v = videoRef.current;
              if (!v) return;
              setVideoOrientation(
                v.videoWidth >= v.videoHeight ? 'landscape' : 'portrait',
              );
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0"
          aria-hidden="true"
        >
          <VideoIcon className="w-5 h-5 text-amber-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-stone-900 truncate">
            {t('watchSummary')}
          </p>
          <p className="text-xs text-stone-500">
            {isActivelyGenerating ? t('generating') : t('notAvailable')}
          </p>
        </div>
        {isActivelyGenerating ? (
          <Loader2
            className="w-5 h-5 text-amber-600 animate-spin flex-shrink-0"
            aria-hidden="true"
          />
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="min-h-11 flex-shrink-0"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            {t('generate')}
          </Button>
        )}
      </div>
      {error && (
        <p className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
