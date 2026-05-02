'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, RefreshCw, Loader2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { LessonSkeleton } from './lesson-skeleton';
import { LessonImage } from './lesson-image';
import { LessonMediaTabs, type LessonMediaTab } from './lesson-media-tabs';
import { SourceImage } from './source-image';
import { SourceCitations } from './source-citations';
import { apiFetch, ApiError, getModuleDetailWithProgress } from '@/lib/api';
import type { SourceImageMeta } from '@/lib/api';
import { SOURCE_IMAGE_RE, splitWithSourceImageMarkers } from '@/lib/source-image-utils';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { useRouter } from 'next/navigation';
import { useLocale } from 'next-intl';
import { track } from '@/lib/analytics';
import { loadLesson, OfflineContentNotAvailable } from '@/lib/offline/content-loader';
import { addOfflineAction } from '@/lib/offline/db';
import { OfflineBadge } from '@/components/shared/offline-badge';
import { useNetworkStatus } from '@/lib/hooks/use-network-status';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;
const UX_SLOW_WARNING_MS = 30 * 1000;

interface LessonContent {
  introduction: string;
  concepts: string[];
  aof_example: string;
  synthesis: string;
  key_points: string[];
  sources_cited: string[];
}

interface LessonData {
  id: string;
  module_id: string;
  unit_id: string;
  language: 'fr' | 'en';
  level: number;
  country_context: string;
  content: LessonContent;
  cached: boolean;
  country_fallback?: boolean;
  source_image_refs?: SourceImageMeta[];
}

interface GeneratingResponse {
  status: 'generating';
  task_id: string;
  message: string;
}

interface LessonViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
  countryContext?: string;
  estimatedMinutes?: number;
  unitTitle?: string;
  unitDescription?: string | null;
  onComplete?: () => void;
}

export function LessonViewer({
  moduleId,
  unitId,
  language,
  level,
  countryContext,
  estimatedMinutes,
  unitTitle,
  unitDescription,
  onComplete,
}: LessonViewerProps) {
  const [lessonData, setLessonData] = useState<LessonData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSlowGeneration, setIsSlowGeneration] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorType, setErrorType] = useState<'load' | 'generation' | 'timeout' | 'no_content' | 'not_found' | null>(null);
  const [forceRegenerate, setForceRegenerate] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [contentSource, setContentSource] = useState<'api' | 'indexeddb'>('api');
  const [isCompleted, setIsCompleted] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);
  // Which media-tab pane is active. The "Actualiser le contenu" button
  // only makes sense on the Lire pane (it regenerates lesson body, not
  // audio/video) so we hide it on listen/watch.
  const [activeMediaTab, setActiveMediaTab] = useState<LessonMediaTab>('read');

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartRef = useRef<number>(0);
  const slowWarningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { user: currentUser, isHydrated } = useCurrentUser();
  const country = countryContext || currentUser?.country || 'CI';
  const router = useRouter();
  const locale = useLocale();
  const { isOnline } = useNetworkStatus();

  const t = useTranslations('LessonViewer');

  useEffect(() => {
    if (!isHydrated || !moduleId || !unitId) return;
    let cancelled = false;
    getModuleDetailWithProgress(moduleId)
      .then((detail) => {
        if (cancelled) return;
        const match = detail.units.find((u) => u.unit_number === unitId);
        if (match?.status === 'completed') setIsCompleted(true);
      })
      .catch((err) => {
        console.warn('Failed to hydrate lesson completion state', err);
      });
    return () => {
      cancelled = true;
    };
  }, [isHydrated, moduleId, unitId]);

  const stopGenerating = (errMsg: string, type: 'load' | 'generation' | 'timeout' | 'no_content') => {
    if (slowWarningTimerRef.current) {
      clearTimeout(slowWarningTimerRef.current);
      slowWarningTimerRef.current = null;
    }
    setIsSlowGeneration(false);
    setIsGenerating(false);
    setIsLoading(false);
    setIsRefreshing(false);
    setError(errMsg);
    setErrorType(type);
  };

  useEffect(() => {
    // Wait for the localStorage-backed user to settle before fetching. Otherwise
    // `country` flips from default → real country mid-mount and re-fires this
    // effect, dispatching a duplicate Celery task for the same logical request.
    if (!isHydrated) return;

    let cancelled = false;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    const pollStatus = (taskId: string, startTime: number) => {
      if (cancelled) return;
      if (Date.now() - startTime > POLL_TIMEOUT_MS) {
        stopGenerating(t('generationTimeout'), 'timeout');
        return;
      }

      pollTimerRef.current = setTimeout(async () => {
        if (cancelled) return;
        try {
          const statusRes = await apiFetch<{ status: string; content_id?: string; error?: string }>(
            `/api/v1/content/status/${taskId}`
          );
          if (cancelled) return;

          if (statusRes.status === 'complete') {
            if (slowWarningTimerRef.current) {
              clearTimeout(slowWarningTimerRef.current);
              slowWarningTimerRef.current = null;
            }
            setIsSlowGeneration(false);
            const lessonRes = await apiFetch<LessonData>(
              `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}`
            );
            if (cancelled) return;
            if ('status' in lessonRes && (lessonRes as unknown as GeneratingResponse).status === 'generating') {
              pollStatus(taskId, startTime);
              return;
            }
            setLessonData(lessonRes);
            setIsGenerating(false);
            setIsLoading(false);
            setIsRefreshing(false);
            setForceRegenerate(false);
          } else if (statusRes.status === 'failed') {
            const rawError = statusRes.error?.trim();
            const isNoContent = rawError?.toLowerCase().includes('no relevant') ||
              rawError?.toLowerCase().includes('rag') ||
              rawError?.toLowerCase().includes('no results') ||
              rawError?.toLowerCase().includes('0 results');
            const fallback = isNoContent ? t('noContentFound') : t('generationFailed');
            const msg = !isNoContent && rawError && rawError.length <= 200 ? rawError : fallback;
            stopGenerating(msg, isNoContent ? 'no_content' : 'generation');
          } else {
            pollStatus(taskId, startTime);
          }
        } catch {
          if (cancelled) return;
          stopGenerating(t('loadError'), 'load');
        }
      }, POLL_INTERVAL_MS);
    };

    const load = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const result = await loadLesson<LessonData | GeneratingResponse>(
          moduleId, unitId, language, level, country, forceRegenerate
        );

        if (cancelled) return;

        setContentSource(result.source);

        const res = result.data;
        if ('status' in res && res.status === 'generating') {
          setIsLoading(false);
          setIsGenerating(true);
          setIsSlowGeneration(false);
          pollStartRef.current = Date.now();
          slowWarningTimerRef.current = setTimeout(() => {
            if (!cancelled) setIsSlowGeneration(true);
          }, UX_SLOW_WARNING_MS);
          pollStatus((res as GeneratingResponse).task_id, pollStartRef.current);
        } else {
          const lesson = res as LessonData;
          setLessonData(lesson);
          setIsLoading(false);
          setIsRefreshing(false);
          setForceRegenerate(false);
          track('lesson_viewed', {
            module_id: lesson.module_id,
            unit_id: lesson.unit_id,
            language: lesson.language,
          });
        }
      } catch (err) {
        if (cancelled) return;
        console.error('Error loading lesson:', err);
        if (err instanceof OfflineContentNotAvailable) {
          setError(t('contentNotAvailableOffline'));
          setErrorType('load');
        } else if (err instanceof ApiError && err.status === 404) {
          setError(t('unitNotFound'));
          setErrorType('not_found');
        } else {
          setError(t('loadError'));
          setErrorType('load');
        }
        setIsLoading(false);
        setIsRefreshing(false);
      }
    };

    load();

    return () => {
      cancelled = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      if (slowWarningTimerRef.current) clearTimeout(slowWarningTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, unitId, language, level, country, forceRegenerate, isHydrated]);

  const handleRetry = () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    if (slowWarningTimerRef.current) clearTimeout(slowWarningTimerRef.current);
    setError(null);
    setErrorType(null);
    setLessonData(null);
    setIsLoading(false);
    setIsGenerating(false);
    setIsSlowGeneration(false);
    setForceRegenerate(false);
    setIsRefreshing(false);
  };

  const handleRefresh = () => {
    setLessonData(null);
    setIsRefreshing(true);
    setForceRegenerate(true);
  };

  const handleMarkComplete = async () => {
    setCompleteError(null);
    try {
      await apiFetch(`/api/v1/progress/complete-lesson`, {
        method: 'POST',
        body: JSON.stringify({
          module_id: moduleId,
          unit_id: unitId,
        }),
      });
      setIsCompleted(true);
      onComplete?.();
    } catch (err) {
      console.error('Error marking lesson complete:', err);
      setCompleteError(t('completeError'));
    }
  };

  const mdClass = "prose prose-gray max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900 prose-table:text-sm";

  const mdComponents = {
    table: ({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) => (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full border-collapse text-sm" {...props}>{children}</table>
      </div>
    ),
    th: ({ children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
      <th className="border border-gray-300 bg-gray-50 px-3 py-2 text-left font-semibold text-gray-900" {...props}>{children}</th>
    ),
    td: ({ children, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
      <td className="border border-gray-300 px-3 py-2 text-gray-700" {...props}>{children}</td>
    ),
    tr: ({ children, ...props }: React.HTMLAttributes<HTMLTableRowElement>) => (
      <tr className="even:bg-gray-50" {...props}>{children}</tr>
    ),
  };


  if (error) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="w-8 h-8 text-red-500 mx-auto mb-3" />
            <div className="text-red-600 font-medium mb-2">{t('error')}</div>
            <p className="text-gray-600 mb-4">{error}</p>
            {errorType === 'no_content' && (
              <p className="text-gray-500 text-sm mb-4">{t('noContentFallback')}</p>
            )}
            {errorType === 'not_found' ? (
              <Button
                variant="outline"
                onClick={() => router.push(`/${locale}/modules/${moduleId}`)}
                className="min-h-11"
              >
                {t('backToModule')}
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={handleRetry}
                className="min-h-11"
              >
                <RefreshCw className="w-4 h-4 mr-2" />
                {t('retry')}
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isGenerating) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Loader2 className="w-10 h-10 animate-spin text-teal-600 mb-4" />
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t('generatingContent')}</h2>
            <p className="text-gray-600 text-center max-w-md">{t('generatingDescription')}</p>
            {isSlowGeneration && (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-amber-600 text-sm text-center max-w-xs">{t('generatingSlowWarning')}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRetry}
                  className="min-h-11 text-amber-700 border-amber-300 hover:bg-amber-50"
                >
                  <RefreshCw className="w-4 h-4 mr-2" />
                  {t('cancelAndRetry')}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isLoading && !lessonData) {
    return <LessonSkeleton />;
  }

  if (!lessonData) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="w-8 h-8 text-red-500 mx-auto mb-3" />
            <div className="text-red-600 font-medium mb-2">{t('error')}</div>
            <p className="text-gray-600 mb-4">{t('noContentFallback')}</p>
            <Button
              variant="outline"
              onClick={handleRetry}
              className="min-h-11"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              {t('retry')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Defensive guard: lessonData may have been set from a non-lesson response
  // (e.g. a 202 generating response with no content field)
  if (!lessonData.content) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="w-8 h-8 text-red-500 mx-auto mb-3" />
            <div className="text-red-600 font-medium mb-2">{t('error')}</div>
            <p className="text-gray-600 mb-4">{t('loadError')}</p>
            <Button
              variant="outline"
              onClick={handleRetry}
              className="min-h-11"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              {t('retry')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { content } = lessonData;

  const sourceImageMap = new Map<string, SourceImageMeta>(
    (lessonData.source_image_refs ?? []).map((img) => [img.id, img])
  );

  function renderContentWithImages(text: string) {
    if (sourceImageMap.size === 0 || !SOURCE_IMAGE_RE.test(text)) {
      SOURCE_IMAGE_RE.lastIndex = 0;
      return (
        <div className={mdClass}>
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{text}</ReactMarkdown>
        </div>
      );
    }
    SOURCE_IMAGE_RE.lastIndex = 0;
    const parts = splitWithSourceImageMarkers(text, sourceImageMap);
    return (
      <>
        {parts.map((part, i) =>
          part.type === 'source_image' ? (
            <SourceImage key={i} {...part.meta} language={lessonData?.language ?? "fr"} />
          ) : (
            <div key={i} className={mdClass}>
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{part.text}</ReactMarkdown>
            </div>
          )
        )}
      </>
    );
  }

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Badge variant="outline">{t('level', { level })}</Badge>
            <div className="flex items-center text-gray-600">
              <Clock className="w-4 h-4 mr-1" />
              {estimatedMinutes ? t('readingTime', { minutes: estimatedMinutes }) : t('readingTimeFallback')}
            </div>
            {contentSource === 'indexeddb' && <OfflineBadge />}
            {lessonData.cached && contentSource !== 'indexeddb' && (
              <Badge variant="secondary">{t('cached')}</Badge>
            )}
            {lessonData.country_fallback && (
              <Badge variant="outline" className="text-amber-600 border-amber-300 bg-amber-50">
                {t('countryFallback')}
              </Badge>
            )}
          </div>
          {activeMediaTab === 'read' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              disabled={isRefreshing || isLoading || isGenerating || !isOnline}
              className="min-h-11 gap-1.5 text-gray-500 hover:text-gray-900"
              title={t('refreshContent')}
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">{t('refreshContent')}</span>
            </Button>
          )}
        </div>
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 mb-1">
          {unitTitle || t('unitTitle', { unit: unitId })}
        </h1>
        {unitTitle && (
          <p className="text-sm text-gray-500 mb-3">
            {t('unitTitle', { unit: unitId })}
          </p>
        )}
        {unitDescription && (
          <p className="text-base text-gray-700 mb-3">{unitDescription}</p>
        )}
      </div>

      <LessonMediaTabs
        lessonId={lessonData.id}
        language={lessonData.language}
        onActiveTabChange={setActiveMediaTab}
        readPane={
          <div className="p-6 md:p-8">
            {/* Lesson Illustration */}
            <LessonImage lessonId={lessonData.id} language={lessonData.language} />

            {/* Introduction */}
            {content.introduction && (
              <div className="mb-8">
                {renderContentWithImages(content.introduction)}
              </div>
            )}

            {/* Key Concepts */}
            <div className="mb-8">
              <div className="space-y-6">
                {content.concepts.map((concept, index) => (
                  <div key={index}>
                    {renderContentWithImages(concept)}
                  </div>
                ))}
              </div>
            </div>

            {/* West African Example */}
            <div className="mb-8 bg-teal-50 border-l-4 border-teal-400 p-6 rounded-r-lg">
              <div className="prose prose-teal max-w-none">
                {renderContentWithImages(content.aof_example)}
              </div>
            </div>

            {/* Synthesis */}
            <div className="mb-8">
              {renderContentWithImages(content.synthesis)}
            </div>

            {/* Key Points */}
            <div className="mb-8">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">
                {t('keyPoints')}
              </h2>
              <ul className="space-y-3">
                {content.key_points.map((point, index) => (
                  <li key={index} className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-teal-500 rounded-full mt-3 flex-shrink-0" />
                    <div className="text-base leading-relaxed text-gray-700 prose prose-gray max-w-none prose-p:text-gray-700 prose-strong:text-gray-900 prose-p:my-0">
                      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>
                        {point}
                      </ReactMarkdown>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        }
      />

      {/* Source Citations */}
      <SourceCitations sources={content.sources_cited} />

      {/* Mark as Complete */}
      <div className="mt-8 text-center">
        <Button
          onClick={handleMarkComplete}
          disabled={isCompleted || isLoading || isGenerating || !isOnline}
          className="min-h-11 px-8"
          size="lg"
        >
          {isCompleted ? (
            <>
              <CheckCircle className="w-4 h-4 mr-2" />
              {t('completed')}
            </>
          ) : (
            t('markComplete')
          )}
        </Button>
        {completeError && (
          <p
            role="alert"
            className="mt-3 inline-flex items-center gap-2 text-sm text-red-600"
          >
            <AlertTriangle className="w-4 h-4" aria-hidden />
            {completeError}
          </p>
        )}
      </div>
    </div>
  );
}