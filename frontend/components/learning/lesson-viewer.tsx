'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, RefreshCw, PlayCircle } from 'lucide-react';
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
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isQuizPassed, setIsQuizPassed] = useState(false);
  const [isCheckingQuiz, setIsCheckingQuiz] = useState(false);
  const [forceRegenerate, setForceRegenerate] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const currentUser = useCurrentUser();
  const country = countryContext || currentUser?.country || 'SN';
  const router = useRouter();
  const locale = useLocale();

  const t = useTranslations('LessonViewer');

  useEffect(() => {
    const checkQuizStatus = async () => {
      setIsCheckingQuiz(true);
      try {
        const status = await checkUnitQuizPassed(moduleId, unitId);
        setIsQuizPassed(status.passed);
      } catch {
        // If check fails, default to not passed (show quiz button)
      } finally {
        setIsCheckingQuiz(false);
      }
    };
    checkQuizStatus();
  }, [moduleId, unitId]);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    
    const startStreaming = async () => {
      try {
        setIsStreaming(true);
        setError(null);
        
        if (!forceRegenerate) {
          // First check if cached content exists
          try {
            const cachedData = await apiFetch<LessonData>(
              `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}`
            );
            
            if (cachedData.cached) {
              setLessonData(cachedData);
              setIsStreaming(false);
              setIsRefreshing(false);
              return;
            }
          } catch (cacheErr) {
            // If cache check fails, continue to streaming
            console.log('Cache check failed, falling back to streaming:', cacheErr);
          }
        }

        // If no cached content or force_regenerate, start streaming
        const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const forceParam = forceRegenerate ? '&force_regenerate=true' : '';
        const streamUrl = `${API_BASE}/api/v1/content/lessons/${moduleId}/${unitId}/stream?language=${language}&level=${level}&country=${country}${forceParam}`;
        eventSource = new EventSource(streamUrl);
        
        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            
            if (data.event === 'chunk') {
              // For now, we'll just handle chunks in the complete event
            } else if (data.event === 'complete') {
              setLessonData(data.data);
              setIsStreaming(false);
              setIsRefreshing(false);
              setForceRegenerate(false);
              eventSource?.close();
            }
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        };
        
        eventSource.onerror = (event) => {
          console.error('SSE error:', event);
          setError(t('streamError'));
          setIsStreaming(false);
          setIsRefreshing(false);
          eventSource?.close();
        };
        
      } catch (err) {
        console.error('Error starting lesson stream:', err);
        setError(t('loadError'));
        setIsStreaming(false);
        setIsRefreshing(false);
      }
    };

    startStreaming();

    return () => {
      eventSource?.close();
    };
  }, [moduleId, unitId, language, level, country, forceRegenerate, t]);

  const handleRefresh = () => {
    setLessonData(null);
    setIsRefreshing(true);
    setForceRegenerate(true);
  };

  const handleValidateWithQuiz = () => {
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
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={isRefreshing || isStreaming}
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
            disabled={isStreaming}
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