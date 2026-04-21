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
export function LessonVideo({ lessonId, language }: LessonVideoProps) {
  const t = useTranslations('LessonVideo');
  const [status, setStatus] = useState<LessonVideoStatus | 'loading' | 'error'>(
    'loading',
  );
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getLessonVideoStatus(lessonId);
      setStatus(data.status);
      if (data.status === 'ready' && data.url) {
        const resolved = data.url.startsWith('/')
          ? `${API_BASE}${data.url}`
          : data.url;
        setVideoUrl(resolved);
      } else {
        setVideoUrl(null);
      }
      return data.status;
    } catch {
      setStatus('error');
      return 'error' as const;
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
      const s = await refresh();
      if (s === 'ready' || s === 'failed' || s === 'error') {
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
    refresh().then((s) => {
      // Already-in-flight generation: pick up the poll loop so the UI
      // transitions without the user clicking again.
      if (s === 'generating' || s === 'pending') {
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
      if (result.status === 'ready') {
        await refresh();
        setIsGenerating(false);
      } else {
        setStatus(result.status);
        startPolling();
      }
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string };
      if (e?.status === 403) {
        setError(t('featureDisabled'));
      } else {
        // Surface the HTTP status + server message when available so
        // operators / testers can diagnose without opening devtools.
        const parts = [t('generateError')];
        if (e?.status) parts.push(`(HTTP ${e.status})`);
        if (e?.message) parts.push(`— ${e.message}`);
        setError(parts.join(' '));
      }
      setIsGenerating(false);
    }
  };

  const isActivelyGenerating =
    isGenerating || status === 'generating' || status === 'pending';

  // Loading / error / pending / failed all fall through to the same
  // "no video yet" card so the learner always sees the Generate
  // button — hiding on error made the component invisible when the
  // status fetch flaked (#1802 post-deploy regression).
  if (status === 'ready' && videoUrl) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm text-stone-600">
          <VideoIcon className="w-4 h-4 text-amber-600" aria-hidden="true" />
          <span>{t('watchSummary')}</span>
        </div>
        <video
          controls
          preload="metadata"
          className="w-full rounded-lg bg-black"
          src={videoUrl}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-stone-200 bg-amber-50/40 p-3">
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
