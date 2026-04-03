'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, RefreshCw, PlayCircle, Loader2, AlertTriangle, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { LessonSkeleton } from './lesson-skeleton';
import { LessonImage } from './lesson-image';
import { SourceCitations } from './source-citations';
import { apiFetch, checkUnitQuizPassed } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { useRouter } from 'next/navigation';
import { useLocale } from 'next-intl';
import { getOfflineContent, upsertOfflineContent, addOfflineAction } from '@/lib/offline/db';
import { useNetworkStatus } from '@/lib/hooks/use-network-status';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

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
  onComplete?: () => void;
}

export function LessonViewer({
  moduleId,
  unitId,
  language,
  level,
  countryContext,
}: LessonViewerProps) {
  const [lessonData, setLessonData] = useState<LessonData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isQuizPassed, setIsQuizPassed] = useState(false);
  const [isCheckingQuiz, setIsCheckingQuiz] = useState(false);
  const [forceRegenerate, setForceRegenerate] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [servedFromCache, setServedFromCache] = useState(false);
  const [offlineUnavailable, setOfflineUnavailable] = useState(false);
  const lessonStartTime = useRef<number>(Date.now());

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartRef = useRef<number>(0);

  const { isOnline } = useNetworkStatus();
  const currentUser = useCurrentUser();
  const country = countryContext || currentUser?.country || 'SN';
  const router = useRouter();
  const locale = useLocale();

  const t = useTranslations('LessonViewer');
  const tOffline = useTranslations('Offline');

  useEffect(() => {
    const checkQuizStatus = async () => {
      setIsCheckingQuiz(true);
      try {
        const quizStatus = await checkUnitQuizPassed(moduleId, unitId);
        setIsQuizPassed(quizStatus.passed);
      } catch {
      } finally {
        setIsCheckingQuiz(false);
      }
    };
    checkQuizStatus();
  }, [moduleId, unitId]);

  const pollStatus = (taskId: string, startTime: number, cacheKey: string) => {
    if (Date.now() - startTime > POLL_TIMEOUT_MS) {
      setIsGenerating(false);
      setIsLoading(false);
      setIsRefreshing(false);
      setError(t('generationTimeout'));
      return;
    }

    pollTimerRef.current = setTimeout(async () => {
      try {
        const statusRes = await apiFetch<{ status: string; content_id?: string; error?: string }>(
          `/api/v1/content/status/${taskId}`
        );

        if (statusRes.status === 'complete') {
          const lessonRes = await apiFetch<LessonData>(
            `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}`
          );
          setLessonData(lessonRes);
          setIsGenerating(false);
          setIsLoading(false);
          setIsRefreshing(false);
          setForceRegenerate(false);
          await upsertOfflineContent({
            unitId: cacheKey,
            moduleId,
            contentType: 'lesson',
            locale: language,
            content: lessonRes,
            cachedAt: Date.now(),
          });
        } else if (statusRes.status === 'failed') {
          setError(t('generationFailed'));
          setIsGenerating(false);
          setIsLoading(false);
          setIsRefreshing(false);
        } else {
          pollStatus(taskId, startTime, cacheKey);
        }
      } catch {
        setError(t('loadError'));
        setIsGenerating(false);
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }, POLL_INTERVAL_MS);
  };

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    const cacheKey = `${moduleId}/${unitId}/${language}/${level}`;

    const load = async () => {
      try {
        setIsLoading(true);
        setError(null);
        setOfflineUnavailable(false);
        lessonStartTime.current = Date.now();

        if (!forceRegenerate) {
          const cached = await getOfflineContent(cacheKey);
          if (cached) {
            setLessonData(cached.content as LessonData);
            setServedFromCache(true);
            setIsLoading(false);
            return;
          }
        }

        if (!isOnline) {
          setOfflineUnavailable(true);
          setIsLoading(false);
          return;
        }

        const forceParam = forceRegenerate ? '&force_regenerate=true' : '';
        const res = await apiFetch<LessonData | GeneratingResponse>(
          `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}${forceParam}`
        );

        if ('status' in res && res.status === 'generating') {
          setIsLoading(false);
          setIsGenerating(true);
          pollStartRef.current = Date.now();
          pollStatus((res as GeneratingResponse).task_id, pollStartRef.current, cacheKey);
        } else {
          const lesson = res as LessonData;
          setLessonData(lesson);
          setServedFromCache(false);
          setIsLoading(false);
          setIsRefreshing(false);
          setForceRegenerate(false);
          await upsertOfflineContent({
            unitId: cacheKey,
            moduleId,
            contentType: 'lesson',
            locale: language,
            content: lesson,
            cachedAt: Date.now(),
          });
        }
      } catch (err) {
        console.error('Error loading lesson:', err);
        setError(t('loadError'));
        setIsLoading(false);
        setIsRefreshing(false);
      }
    };

    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, unitId, language, level, country, forceRegenerate]);

  const handleRefresh = () => {
    setLessonData(null);
    setIsRefreshing(true);
    setForceRegenerate(true);
  };

  const handleValidateWithQuiz = async () => {
    const timeSpent = Math.floor((Date.now() - lessonStartTime.current) / 1000);
    if (!isOnline) {
      await addOfflineAction({
        actionType: 'lesson_complete',
        payload: { module_id: moduleId, unit_id: unitId, time_spent_seconds: timeSpent },
      });
    }
    router.push(`/${locale}/modules/${moduleId}/quiz?unit=${unitId}`);
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
            <Button
              variant="outline"
              onClick={() => { setError(null); setLessonData(null); setForceRegenerate(false); setIsLoading(false); setIsGenerating(false); }}
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

  if (offlineUnavailable) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-gray-200">
          <CardContent className="p-6 text-center">
            <WifiOff className="w-8 h-8 text-gray-400 mx-auto mb-3" />
            <div className="text-gray-800 font-medium mb-2">{tOffline('unavailableTitle')}</div>
            <p className="text-gray-600">{tOffline('unavailableLesson')}</p>
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
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isLoading && !lessonData) {
    return <LessonSkeleton />;
  }

  if (!lessonData) {
    return <LessonSkeleton />;
  }

  const { content } = lessonData;

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Badge variant="outline">{t('level', { level })}</Badge>
            <div className="flex items-center text-gray-600">
              <Clock className="w-4 h-4 mr-1" />
              {t('readingTime')}
            </div>
            {lessonData.cached && (
              <Badge variant="secondary">{t('cached')}</Badge>
            )}
            {servedFromCache && (
              <Badge variant="secondary" className="flex items-center gap-1">
                <WifiOff className="w-3 h-3" />
                {tOffline('badge')}
              </Badge>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={isRefreshing || isLoading || isGenerating}
            className="min-h-11 gap-1.5 text-gray-500 hover:text-gray-900"
            title={t('refreshContent')}
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">{t('refreshContent')}</span>
          </Button>
        </div>
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 mb-3">
          {t('unitTitle', { unit: unitId })}
        </h1>
      </div>

      {/* Main Content */}
      <Card className="mb-6">
        <CardContent className="p-6 md:p-8">
          {/* Introduction */}
          <div className="mb-8">
            <div className={mdClass}>
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.introduction}</ReactMarkdown>
            </div>
          </div>

          {/* Lesson Illustration */}
          <LessonImage lessonId={lessonData.id} language={lessonData.language} />

          {/* Key Concepts */}
          <div className="mb-8">
            <div className="space-y-6">
              {content.concepts.map((concept, index) => (
                <div key={index} className={mdClass}>
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{concept}</ReactMarkdown>
                </div>
              ))}
            </div>
          </div>

          {/* West African Example */}
          <div className="mb-8 bg-teal-50 border-l-4 border-teal-400 p-6 rounded-r-lg">
            <div className="prose prose-teal max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.aof_example}</ReactMarkdown>
            </div>
          </div>

          {/* Synthesis */}
          <div className="mb-8">
            <div className={mdClass}>
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.synthesis}</ReactMarkdown>
            </div>
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
                  <span className="text-base leading-relaxed text-gray-700">
                    {point}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      {/* Source Citations */}
      <SourceCitations sources={content.sources_cited} />

      {/* Quiz Validation */}
      <div className="mt-8 text-center">
        {isCheckingQuiz ? (
          <div className="inline-flex items-center gap-2 text-gray-500 text-sm">
            <RefreshCw className="w-4 h-4 animate-spin" />
            {t('checkingStatus')}
          </div>
        ) : isQuizPassed ? (
          <div
            role="status"
            className="inline-flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 font-medium px-6 py-3 rounded-lg"
          >
            <CheckCircle className="w-5 h-5" />
            {t('completed')}
          </div>
        ) : (
          <Button
            onClick={handleValidateWithQuiz}
            disabled={isLoading || isGenerating}
            className="min-h-11 px-8 bg-teal-600 hover:bg-teal-700"
            size="lg"
          >
            <PlayCircle className="w-4 h-4 mr-2" />
            {t('validateWithQuiz')}
          </Button>
        )}
      </div>
    </div>
  );
}