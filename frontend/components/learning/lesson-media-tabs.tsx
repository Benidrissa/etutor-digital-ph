'use client';

import { useCallback, useState, type ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import { BookOpen, Headphones, Video as VideoIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { LessonAudio } from './lesson-audio';
import { LessonVideo } from './lesson-video';

export type LessonMediaTab = 'read' | 'listen' | 'watch';

interface LessonMediaTabsProps {
  lessonId: string;
  language: 'fr' | 'en';
  /** The lesson body — illustration, intro, concepts, AOF example, synthèse, key points. */
  readPane: ReactNode;
  /** Fires whenever the active tab changes — lets the parent hide chrome (e.g. the refresh button) on the listen/watch panes. */
  onActiveTabChange?: (tab: LessonMediaTab) => void;
}

/**
 * Three-tab media region — Lire / Écouter / Regarder — that unifies the
 * three modalities of consuming a lesson. All panes are kept mounted via
 * Base UI's ``keepMounted`` so audio polling, audio playback continuity,
 * and video status badging survive tab switches.
 */
export function LessonMediaTabs({
  lessonId,
  language,
  readPane,
  onActiveTabChange,
}: LessonMediaTabsProps) {
  const t = useTranslations('LessonMediaTabs');
  const [audioDuration, setAudioDuration] = useState<number | null>(null);
  const [isVideoGenerating, setIsVideoGenerating] = useState(false);

  const handleValueChange = useCallback(
    (value: unknown) => {
      const tab = value as LessonMediaTab;
      onActiveTabChange?.(tab);
    },
    [onActiveTabChange],
  );

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <Tabs
      defaultValue="read"
      onValueChange={handleValueChange}
      className="mb-6 gap-3"
    >
      <TabsList className="h-auto w-full justify-start gap-1 rounded-lg bg-muted p-1 overflow-x-auto">
        <TabsTrigger
          value="read"
          className="min-h-11 flex-none gap-2 px-4 data-active:bg-background"
        >
          <BookOpen className="w-4 h-4" aria-hidden="true" />
          <span>{t('readTab')}</span>
        </TabsTrigger>
        <TabsTrigger
          value="listen"
          className="min-h-11 flex-none gap-2 px-4 data-active:bg-background"
        >
          <Headphones className="w-4 h-4" aria-hidden="true" />
          <span>
            {t('listenTab')}
            {audioDuration !== null && (
              <span className="text-muted-foreground ml-1 tabular-nums">
                ({formatDuration(audioDuration)})
              </span>
            )}
          </span>
        </TabsTrigger>
        <TabsTrigger
          value="watch"
          className="min-h-11 flex-none gap-2 px-4 data-active:bg-background"
        >
          <VideoIcon className="w-4 h-4" aria-hidden="true" />
          <span>{t('watchTab')}</span>
          {isVideoGenerating && (
            <span className="ml-1 inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-normal text-amber-700">
              {t('generatingBadge')}
            </span>
          )}
        </TabsTrigger>
      </TabsList>

      <Card>
        <CardContent className="p-0">
          <TabsContent
            value="read"
            keepMounted
            className="data-active:min-h-[40vh]"
          >
            {readPane}
          </TabsContent>
          <TabsContent
            value="listen"
            keepMounted
            className="data-active:min-h-[40vh] p-6 md:p-8"
          >
            <LessonAudio
              lessonId={lessonId}
              language={language}
              onDurationChange={setAudioDuration}
            />
          </TabsContent>
          <TabsContent
            value="watch"
            keepMounted
            className="data-active:min-h-[40vh] p-6 md:p-8"
          >
            <LessonVideo
              lessonId={lessonId}
              language={language}
              onActivelyGeneratingChange={setIsVideoGenerating}
            />
          </TabsContent>
        </CardContent>
      </Card>
    </Tabs>
  );
}
