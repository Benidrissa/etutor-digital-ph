'use client';

import { useCallback, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { useTranslations } from 'next-intl';
import { BookOpen, Headphones, ScrollText, Video as VideoIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { LessonAudio } from './lesson-audio';
import { LessonStorySkeleton } from './lesson-story-skeleton';
import { LessonVideo } from './lesson-video';

/**
 * The Story tab's panel and the whole story player behind it (~10 KB gzipped)
 * load only once a learner first opens the tab, so the lesson page stays
 * inside its JS budget on 2G. Client-only: the panel needs the learner's
 * stored name and fetches nothing on the server anyway.
 */
const LessonStory = dynamic(
  () => import('./lesson-story').then((mod) => mod.LessonStory),
  { ssr: false, loading: () => <LessonStorySkeleton /> },
);

export type LessonMediaTab = 'read' | 'listen' | 'watch' | 'story';

interface LessonMediaTabsProps {
  lessonId: string;
  /** The module and unit the lesson belongs to — the story is looked up by them. */
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  /** The lesson body — illustration, intro, concepts, AOF example, synthèse, key points. */
  readPane: ReactNode;
  /** Fires whenever the active tab changes — lets the parent hide chrome (e.g. the refresh button) on the listen/watch/story panes. */
  onActiveTabChange?: (tab: LessonMediaTab) => void;
  /**
   * Fires once when the learner finishes the lesson's story. Story mode is a
   * tab on the lesson unit, not a unit of its own, so finishing it completes
   * this lesson — the parent records that through its usual completion path.
   */
  onStoryComplete?: () => void;
}

/**
 * Four-tab media region — Lire / Écouter / Vidéo / Histoire — that unifies
 * the ways of consuming a lesson. All panes are kept mounted via Base UI's
 * ``keepMounted`` so audio polling, audio playback continuity, video status
 * badging and the learner's place in the story survive tab switches. The
 * story pane's code is split out and loaded the first time its tab opens;
 * after that it is told whether it is the open tab, so a running mini-game
 * pauses while the learner reads another tab.
 */
export function LessonMediaTabs({
  lessonId,
  moduleId,
  unitId,
  language,
  readPane,
  onActiveTabChange,
  onStoryComplete,
}: LessonMediaTabsProps) {
  const t = useTranslations('LessonMediaTabs');
  const [activeTab, setActiveTab] = useState<LessonMediaTab>('read');
  const [audioDuration, setAudioDuration] = useState<number | null>(null);
  const [isVideoGenerating, setIsVideoGenerating] = useState(false);
  const [isStoryGenerating, setIsStoryGenerating] = useState(false);
  // Latches the first time the Story tab is opened (state adjusted during
  // render, so the panel's code starts loading in the same commit).
  const [storyOpened, setStoryOpened] = useState(false);
  if (activeTab === 'story' && !storyOpened) setStoryOpened(true);

  const handleValueChange = useCallback(
    (value: unknown) => {
      const tab = value as LessonMediaTab;
      setActiveTab(tab);
      onActiveTabChange?.(tab);
    },
    [onActiveTabChange],
  );

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const generatingBadge = (
    <span className="ml-1 inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-normal text-amber-700">
      {t('generatingBadge')}
    </span>
  );

  return (
    <Tabs
      defaultValue="read"
      onValueChange={handleValueChange}
      className="mb-6 gap-3"
    >
      <TabsList className="group-data-horizontal/tabs:h-auto min-h-12 w-full justify-start gap-1 rounded-lg bg-muted p-1 overflow-x-auto overflow-y-hidden">
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
          {isVideoGenerating && generatingBadge}
        </TabsTrigger>
        <TabsTrigger
          value="story"
          className="min-h-11 flex-none gap-2 px-4 data-active:bg-background"
        >
          <ScrollText className="w-4 h-4" aria-hidden="true" />
          <span>{t('storyTab')}</span>
          {isStoryGenerating && generatingBadge}
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
          <TabsContent
            value="story"
            keepMounted
            className="data-active:min-h-[40vh] p-4 md:p-8"
          >
            {/* Keyed by lesson so a different lesson or language starts fresh.
                Not rendered (so not downloaded) until the tab is first opened. */}
            {storyOpened ? (
              <LessonStory
                key={`${moduleId}:${unitId}:${language}`}
                moduleId={moduleId}
                unitId={unitId}
                language={language}
                active={activeTab === 'story'}
                onActivelyGeneratingChange={setIsStoryGenerating}
                onComplete={onStoryComplete}
              />
            ) : null}
          </TabsContent>
        </CardContent>
      </Card>
    </Tabs>
  );
}
