'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LessonSkeleton } from './lesson-skeleton';
import { SourceCitations } from './source-citations';
import { apiFetch } from '@/lib/api';
import {
  getContentFromDB,
  saveContentToDB,
  queueOfflineAction,
  isOnline,
} from '@/lib/offline/content-loader';

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

interface LessonViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
  countryContext: string;
  onComplete?: () => void;
}

export function LessonViewer({
  moduleId,
  unitId,
  language,
  level,
  countryContext,
  onComplete
}: LessonViewerProps) {
  const [lessonData, setLessonData] = useState<LessonData | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCompleted, setIsCompleted] = useState(false);
  const [servedFromCache, setServedFromCache] = useState(false);
  const [notAvailableOffline, setNotAvailableOffline] = useState(false);
  const lessonStartTime = useRef<number>(0);

  const t = useTranslations('LessonViewer');

  useEffect(() => {
    let eventSource: EventSource | null = null;
    lessonStartTime.current = typeof Date !== 'undefined' ? Date.now() : 0;

    const loadLesson = async () => {
      try {
        setIsStreaming(true);
        setError(null);
        setNotAvailableOffline(false);

        // 1. Check IndexedDB first
        const cached = await getContentFromDB<LessonData>(
          moduleId, unitId, language, level, countryContext, 'lesson'
        );
        if (cached) {
          setLessonData(cached);
          setServedFromCache(true);
          setIsStreaming(false);
          return;
        }

        // 2. If offline and not in IndexedDB — show unavailable message
        if (!isOnline()) {
          setNotAvailableOffline(true);
          setIsStreaming(false);
          return;
        }

        // 3. Try API cache
        try {
          const cachedData = await apiFetch<LessonData>(
            `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${countryContext}`
          );

          if (cachedData.cached) {
            setLessonData(cachedData);
            setServedFromCache(false);
            setIsStreaming(false);
            await saveContentToDB(moduleId, unitId, language, level, countryContext, 'lesson', cachedData);
            return;
          }
        } catch {
          // Cache check failed — continue to streaming
        }

        // 4. Stream generation
        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const streamUrl = `${API_BASE}/api/v1/content/lessons/${moduleId}/${unitId}/stream?language=${language}&level=${level}&country=${countryContext}`;
        eventSource = new EventSource(streamUrl);

        eventSource.onmessage = async (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.event === 'complete') {
              setLessonData(data.data);
              setIsStreaming(false);
              eventSource?.close();
              await saveContentToDB(moduleId, unitId, language, level, countryContext, 'lesson', data.data);
            }
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        };

        eventSource.onerror = () => {
          setError(t('streamError'));
          setIsStreaming(false);
          eventSource?.close();
        };
      } catch {
        setError(t('loadError'));
        setIsStreaming(false);
      }
    };

    loadLesson();

    return () => {
      eventSource?.close();
    };
  }, [moduleId, unitId, language, level, countryContext, t]);

  const handleMarkComplete = async () => {
    const timeSpentSeconds = Math.floor((Date.now() - lessonStartTime.current) / 1000);

    if (!isOnline()) {
      await queueOfflineAction({
        type: 'lesson_progress',
        payload: {
          module_id: moduleId,
          unit_id: unitId,
          time_spent_seconds: timeSpentSeconds,
          completed: true,
        },
        created_at: new Date().toISOString(),
      });
      setIsCompleted(true);
      onComplete?.();
      return;
    }

    try {
      await apiFetch(`/api/v1/progress/complete-lesson`, {
        method: 'POST',
        body: JSON.stringify({
          module_id: moduleId,
          unit_id: unitId,
          time_spent_seconds: timeSpentSeconds,
        })
      });
      setIsCompleted(true);
      onComplete?.();
    } catch {
      // Queue for later sync on network failure
      await queueOfflineAction({
        type: 'lesson_progress',
        payload: {
          module_id: moduleId,
          unit_id: unitId,
          time_spent_seconds: timeSpentSeconds,
          completed: true,
        },
        created_at: new Date().toISOString(),
      });
      setIsCompleted(true);
      onComplete?.();
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

  if (notAvailableOffline) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-amber-200">
          <CardContent className="p-6 text-center">
            <WifiOff className="w-10 h-10 text-amber-500 mx-auto mb-3" />
            <div className="text-amber-700 font-medium mb-2">{t('offlineUnavailableTitle')}</div>
            <p className="text-gray-600">{t('offlineUnavailable')}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-600 font-medium mb-2">{t('error')}</div>
            <p className="text-gray-600">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isStreaming && !lessonData) {
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
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <Badge variant="outline">{t('level', { level })}</Badge>
          <div className="flex items-center text-gray-600">
            <Clock className="w-4 h-4 mr-1" />
            {t('readingTime')}
          </div>
          {lessonData.cached && (
            <Badge variant="secondary">{t('cached')}</Badge>
          )}
          {servedFromCache && (
            <Badge variant="secondary" className="flex items-center gap-1 bg-amber-50 text-amber-700 border-amber-200">
              <WifiOff className="w-3 h-3" />
              {t('offlineBadge')}
            </Badge>
          )}
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
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{content.introduction}</ReactMarkdown>
            </div>
          </div>

          {/* Key Concepts */}
          <div className="mb-8">
            <div className="space-y-6">
              {content.concepts.map((concept, index) => (
                <div key={index} className={mdClass}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{concept}</ReactMarkdown>
                </div>
              ))}
            </div>
          </div>

          {/* West African Example */}
          <div className="mb-8 bg-teal-50 border-l-4 border-teal-400 p-6 rounded-r-lg">
            <div className="prose prose-teal max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{content.aof_example}</ReactMarkdown>
            </div>
          </div>

          {/* Synthesis */}
          <div className="mb-8">
            <div className={mdClass}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{content.synthesis}</ReactMarkdown>
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

      {/* Mark as Complete Button */}
      <div className="mt-8 text-center">
        <Button
          onClick={handleMarkComplete}
          disabled={isCompleted || isStreaming}
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
      </div>
    </div>
  );
}
