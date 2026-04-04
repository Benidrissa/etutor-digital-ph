'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Film, Headphones, Loader2, RefreshCw, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  generateModuleMedia,
  getModuleMedia,
  ModuleMediaRecord,
  pollMediaStatus,
} from '@/lib/module-media-api';
import { ModuleAudioPlayer } from './module-audio-player';
import { ModuleVideoPlayer } from './module-video-player';

interface ModuleMediaSectionProps {
  moduleId: string;
  language: 'fr' | 'en';
  isAdmin?: boolean;
}

export function ModuleMediaSection({
  moduleId,
  language,
  isAdmin = false,
}: ModuleMediaSectionProps) {
  const t = useTranslations('ModuleMedia');
  const [audioRecord, setAudioRecord] = useState<ModuleMediaRecord | null>(null);
  const [videoRecord, setVideoRecord] = useState<ModuleMediaRecord | null>(null);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const [isLoadingVideo, setIsLoadingVideo] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);

  const loadMedia = useCallback(async () => {
    try {
      const data = await getModuleMedia(moduleId);
      const audio = data.media.find(
        (m) => m.media_type === 'audio_summary' && m.language === language
      ) ?? null;
      const video = data.media.find(
        (m) => m.media_type === 'video_summary' && m.language === language
      ) ?? null;
      setAudioRecord(audio);
      setVideoRecord(video);
    } catch {
    } finally {
      setIsInitialLoading(false);
    }
  }, [moduleId, language]);

  useEffect(() => {
    loadMedia();
  }, [loadMedia]);

  useEffect(() => {
    const pollRecord = async (record: ModuleMediaRecord) => {
      try {
        const statusUpdate = await pollMediaStatus(moduleId, record.id);
        const merged: ModuleMediaRecord = {
          ...record,
          status: statusUpdate.status,
          url: statusUpdate.url,
        };
        if (record.media_type === 'audio_summary') setAudioRecord(merged);
        else setVideoRecord(merged);
      } catch {}
    };

    const intervals: ReturnType<typeof setInterval>[] = [];

    if (audioRecord && (audioRecord.status === 'pending' || audioRecord.status === 'generating')) {
      const rec = audioRecord;
      intervals.push(setInterval(() => pollRecord(rec), 4000));
    }

    if (videoRecord && (videoRecord.status === 'pending' || videoRecord.status === 'generating')) {
      const rec = videoRecord;
      intervals.push(setInterval(() => pollRecord(rec), 4000));
    }

    return () => {
      intervals.forEach(clearInterval);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, audioRecord?.status, videoRecord?.status]);

  const handleGenerateAudio = async (force = false) => {
    setIsLoadingAudio(true);
    try {
      const result = await generateModuleMedia(moduleId, 'audio_summary', language, force);
      setAudioRecord((prev) =>
        prev
          ? { ...prev, status: 'pending', id: result.media_id }
          : {
              id: result.media_id,
              module_id: moduleId,
              media_type: 'audio_summary',
              language,
              status: 'pending',
              url: null,
              duration_seconds: null,
              file_size_bytes: null,
              mime_type: null,
              generated_at: null,
              created_at: new Date().toISOString(),
            }
      );
    } catch {
    } finally {
      setIsLoadingAudio(false);
    }
  };

  const handleGenerateVideo = async (force = false) => {
    setIsLoadingVideo(true);
    try {
      const result = await generateModuleMedia(moduleId, 'video_summary', language, force);
      setVideoRecord((prev) =>
        prev
          ? { ...prev, status: 'pending', id: result.media_id }
          : {
              id: result.media_id,
              module_id: moduleId,
              media_type: 'video_summary',
              language,
              status: 'pending',
              url: null,
              duration_seconds: null,
              file_size_bytes: null,
              mime_type: null,
              generated_at: null,
              created_at: new Date().toISOString(),
            }
      );
    } catch {
    } finally {
      setIsLoadingVideo(false);
    }
  };

  if (isInitialLoading) {
    return (
      <div className="space-y-3">
        <div className="h-16 animate-pulse rounded-xl bg-stone-100" />
        <div className="h-16 animate-pulse rounded-xl bg-stone-100" />
      </div>
    );
  }

  const noMedia = !audioRecord && !videoRecord;
  if (noMedia && !isAdmin) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-teal-600" />
          {t('sectionTitle')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <Headphones className="h-4 w-4" />
              {t('audioSummary')}
            </div>
            {isAdmin && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                disabled={
                  isLoadingAudio ||
                  audioRecord?.status === 'pending' ||
                  audioRecord?.status === 'generating'
                }
                onClick={() => handleGenerateAudio(audioRecord?.status === 'ready')}
              >
                {isLoadingAudio ||
                audioRecord?.status === 'pending' ||
                audioRecord?.status === 'generating' ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : audioRecord?.status === 'ready' ? (
                  <RefreshCw className="mr-1 h-3 w-3" />
                ) : (
                  <Sparkles className="mr-1 h-3 w-3" />
                )}
                {audioRecord?.status === 'ready' ? t('regenerate') : t('generate')}
              </Button>
            )}
          </div>

          {!audioRecord && !isAdmin && null}

          {!audioRecord && isAdmin && (
            <p className="text-xs text-stone-500">{t('notGenerated')}</p>
          )}

          {audioRecord && (audioRecord.status === 'pending' || audioRecord.status === 'generating') && (
            <div className="flex items-center gap-2 rounded-lg border border-teal-100 bg-teal-50 px-3 py-2">
              <Loader2 className="h-4 w-4 animate-spin text-teal-600 flex-shrink-0" />
              <p className="text-sm text-teal-700">{t('generating')}</p>
            </div>
          )}

          {audioRecord && audioRecord.status === 'failed' && (
            <div className="flex items-center justify-between rounded-lg border border-red-100 bg-red-50 px-3 py-2">
              <p className="text-sm text-red-600">{t('generationFailed')}</p>
              {isAdmin && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs text-red-600"
                  onClick={() => handleGenerateAudio(true)}
                >
                  {t('retry')}
                </Button>
              )}
            </div>
          )}

          {audioRecord && audioRecord.status === 'ready' && (
            <ModuleAudioPlayer
              mediaId={audioRecord.id}
              moduleId={moduleId}
              language={language}
              durationSeconds={audioRecord.duration_seconds ?? undefined}
            />
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
              <Film className="h-4 w-4" />
              {t('videoSummary')}
            </div>
            {isAdmin && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                disabled={
                  isLoadingVideo ||
                  videoRecord?.status === 'pending' ||
                  videoRecord?.status === 'generating'
                }
                onClick={() => handleGenerateVideo(videoRecord?.status === 'ready')}
              >
                {isLoadingVideo ||
                videoRecord?.status === 'pending' ||
                videoRecord?.status === 'generating' ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : videoRecord?.status === 'ready' ? (
                  <RefreshCw className="mr-1 h-3 w-3" />
                ) : (
                  <Sparkles className="mr-1 h-3 w-3" />
                )}
                {videoRecord?.status === 'ready' ? t('regenerate') : t('generate')}
              </Button>
            )}
          </div>

          {!videoRecord && isAdmin && (
            <p className="text-xs text-stone-500">{t('notGenerated')}</p>
          )}

          {videoRecord && (videoRecord.status === 'pending' || videoRecord.status === 'generating') && (
            <div className="flex items-center gap-2 rounded-lg border border-teal-100 bg-teal-50 px-3 py-2">
              <Loader2 className="h-4 w-4 animate-spin text-teal-600 flex-shrink-0" />
              <p className="text-sm text-teal-700">{t('generating')}</p>
            </div>
          )}

          {videoRecord && videoRecord.status === 'failed' && (
            <div className="flex items-center justify-between rounded-lg border border-red-100 bg-red-50 px-3 py-2">
              <p className="text-sm text-red-600">{t('generationFailed')}</p>
              {isAdmin && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs text-red-600"
                  onClick={() => handleGenerateVideo(true)}
                >
                  {t('retry')}
                </Button>
              )}
            </div>
          )}

          {videoRecord && videoRecord.status === 'ready' && (
            <ModuleVideoPlayer
              mediaId={videoRecord.id}
              moduleId={moduleId}
              language={language}
              durationSeconds={videoRecord.duration_seconds ?? undefined}
              mimeType={videoRecord.mime_type ?? undefined}
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
