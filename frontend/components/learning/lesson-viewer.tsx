'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, Loader2, BookOpenCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import { LessonSkeleton } from './lesson-skeleton';
import { SourceCitations } from './source-citations';
import { LessonQuiz } from '@/components/quiz/lesson-quiz';
import { apiFetch, generateLessonValidationQuiz } from '@/lib/api';
import type { Quiz } from '@/lib/api';

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

type ViewerStage = 'lesson' | 'quiz';

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
  const [stage, setStage] = useState<ViewerStage>('lesson');
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [quizError, setQuizError] = useState<string | null>(null);

  const t = useTranslations('LessonViewer');

  useEffect(() => {
    let eventSource: EventSource | null = null;
    
    const startStreaming = async () => {
      try {
        setIsStreaming(true);
        setError(null);
        
        try {
          const cachedData = await apiFetch<LessonData>(
            `/api/v1/content/lessons/${moduleId}/${unitId}?language=${language}&level=${level}&country=${countryContext}`
          );
          
          if (cachedData.cached) {
            setLessonData(cachedData);
            setIsStreaming(false);
            return;
          }
        } catch (cacheErr) {
          console.log('Cache check failed, falling back to streaming:', cacheErr);
        }

        const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const streamUrl = `${API_BASE}/api/v1/content/lessons/${moduleId}/${unitId}/stream?language=${language}&level=${level}&country=${countryContext}`;
        eventSource = new EventSource(streamUrl);
        
        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            
            if (data.event === 'chunk') {
              // For now, we'll just handle chunks in the complete event
            } else if (data.event === 'complete') {
              setLessonData(data.data);
              setIsStreaming(false);
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
          eventSource?.close();
        };
        
      } catch (err) {
        console.error('Error starting lesson stream:', err);
        setError(t('loadError'));
        setIsStreaming(false);
      }
    };

    startStreaming();

    return () => {
      eventSource?.close();
    };
  }, [moduleId, unitId, language, level, countryContext, t]);

  const handleStartQuiz = async () => {
    setIsGeneratingQuiz(true);
    setQuizError(null);

    try {
      const generatedQuiz = await generateLessonValidationQuiz({
        module_id: moduleId,
        unit_id: unitId,
        language,
        country: countryContext,
        level,
      });
      setQuiz(generatedQuiz);
      setStage('quiz');
    } catch (err) {
      console.error('Error generating validation quiz:', err);
      setQuizError(t('quizGenerateError'));
    } finally {
      setIsGeneratingQuiz(false);
    }
  };

  const handleRetryQuiz = async () => {
    setQuiz(null);
    await handleStartQuiz();
  };

  const handleReviewLesson = () => {
    setStage('lesson');
  };

  const handleQuizComplete = () => {
    setIsCompleted(true);
    onComplete?.();
  };

  const mdClass = "prose prose-gray max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900 prose-table:text-sm";

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
        <div className="flex items-center gap-3 mb-3">
          <Badge variant="outline">{t('level', { level })}</Badge>
          <div className="flex items-center text-gray-600">
            <Clock className="w-4 h-4 mr-1" />
            {t('readingTime')}
          </div>
          {lessonData.cached && (
            <Badge variant="secondary">{t('cached')}</Badge>
          )}
        </div>
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 mb-3">
          {t('unitTitle', { unit: unitId })}
        </h1>
      </div>

      {stage === 'lesson' ? (
        <>
          {/* Main Content */}
          <Card className="mb-6">
            <CardContent className="p-6 md:p-8">
              {/* Introduction */}
              <div className="mb-8">
                <div className={mdClass}>
                  <ReactMarkdown>{content.introduction}</ReactMarkdown>
                </div>
              </div>

              {/* Key Concepts */}
              <div className="mb-8">
                <div className="space-y-6">
                  {content.concepts.map((concept, index) => (
                    <div key={index} className={mdClass}>
                      <ReactMarkdown>{concept}</ReactMarkdown>
                    </div>
                  ))}
                </div>
              </div>

              {/* West African Example */}
              <div className="mb-8 bg-teal-50 border-l-4 border-teal-400 p-6 rounded-r-lg">
                <div className="prose prose-teal max-w-none">
                  <ReactMarkdown>{content.aof_example}</ReactMarkdown>
                </div>
              </div>

              {/* Synthesis */}
              <div className="mb-8">
                <div className={mdClass}>
                  <ReactMarkdown>{content.synthesis}</ReactMarkdown>
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

          {/* Validate Knowledge Button */}
          <div className="mt-8 text-center space-y-3">
            {isCompleted ? (
              <div className="flex items-center justify-center gap-2 text-green-700 font-medium">
                <CheckCircle className="w-5 h-5" aria-hidden="true" />
                <span>{t('completed')}</span>
              </div>
            ) : (
              <>
                <Button
                  onClick={handleStartQuiz}
                  disabled={isGeneratingQuiz || isStreaming}
                  className="min-h-11 px-8 bg-teal-600 hover:bg-teal-700"
                  size="lg"
                >
                  {isGeneratingQuiz ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                      {t('generatingQuiz')}
                    </>
                  ) : (
                    <>
                      <BookOpenCheck className="w-5 h-5 mr-2" aria-hidden="true" />
                      {t('validateKnowledge')}
                    </>
                  )}
                </Button>

                {quizError && (
                  <p className="text-sm text-red-600" role="alert">
                    {quizError}
                  </p>
                )}
              </>
            )}
          </div>
        </>
      ) : (
        /* Quiz Stage */
        quiz && (
          <div className="mt-2">
            <LessonQuiz
              quiz={quiz}
              moduleId={moduleId}
              unitId={unitId}
              onRetry={handleRetryQuiz}
              onReviewLesson={handleReviewLesson}
              onComplete={handleQuizComplete}
            />
          </div>
        )
      )}
    </div>
  );
}
