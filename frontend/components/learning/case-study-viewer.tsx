'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import { LessonSkeleton } from './lesson-skeleton';
import { SourceCitations } from './source-citations';
import { apiFetch } from '@/lib/api';

interface CaseStudyContent {
  aof_context: string;
  real_data: string;
  guided_questions: string[];
  annotated_correction: string;
  sources_cited: string[];
}

interface CaseStudyData {
  id: string;
  module_id: string;
  unit_id: string;
  content_type: 'case';
  language: 'fr' | 'en';
  level: number;
  country_context: string;
  content: CaseStudyContent;
  cached: boolean;
}

interface CaseStudyViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
  countryContext: string;
  onComplete?: () => void;
}

export function CaseStudyViewer({
  moduleId,
  unitId,
  language,
  level,
  countryContext,
  onComplete,
}: CaseStudyViewerProps) {
  const [caseStudyData, setCaseStudyData] = useState<CaseStudyData | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCompleted, setIsCompleted] = useState(false);
  const [correctionVisible, setCorrectionVisible] = useState(false);

  const t = useTranslations('CaseStudyViewer');

  useEffect(() => {
    let eventSource: EventSource | null = null;

    const startStreaming = async () => {
      try {
        setIsStreaming(true);
        setError(null);

        try {
          const cachedData = await apiFetch<CaseStudyData>(
            `/api/v1/content/cases/${moduleId}/${unitId}?language=${language}&level=${level}&country=${countryContext}`
          );

          if (cachedData.cached) {
            setCaseStudyData(cachedData);
            setIsStreaming(false);
            return;
          }
        } catch {
        }

        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const streamUrl = `${API_BASE}/api/v1/content/cases/${moduleId}/${unitId}/stream?language=${language}&level=${level}&country=${countryContext}`;
        eventSource = new EventSource(streamUrl);

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.event === 'complete') {
              setCaseStudyData(data.data);
              setIsStreaming(false);
              eventSource?.close();
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

    startStreaming();

    return () => {
      eventSource?.close();
    };
  }, [moduleId, unitId, language, level, countryContext, t]);

  const handleMarkComplete = async () => {
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
      console.error('Error marking case study complete:', err);
    }
  };

  const mdClass =
    'prose prose-gray max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900 prose-table:text-sm';

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

  if (isStreaming && !caseStudyData) {
    return <LessonSkeleton />;
  }

  if (!caseStudyData) {
    return <LessonSkeleton />;
  }

  const { content } = caseStudyData;

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <Badge variant="outline" className="flex items-center gap-1">
            <FileText className="w-3 h-3" />
            {t('badge')}
          </Badge>
          <Badge variant="outline">{t('level', { level })}</Badge>
          <div className="flex items-center text-gray-600">
            <Clock className="w-4 h-4 mr-1" />
            {t('estimatedTime')}
          </div>
          {caseStudyData.cached && <Badge variant="secondary">{t('cached')}</Badge>}
        </div>
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 mb-3">
          {t('unitTitle', { unit: unitId })}
        </h1>
      </div>

      {/* Section 1 — AOF Context */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg text-teal-700">{t('aofContext')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className={mdClass}>
            <ReactMarkdown>{content.aof_context}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>

      {/* Section 2 — Real Data */}
      <Card className="mb-6 border-amber-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg text-amber-700">{t('realData')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className={`${mdClass} bg-amber-50 rounded-lg p-4`}>
            <ReactMarkdown>{content.real_data}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>

      {/* Section 3 — Guided Questions */}
      <Card className="mb-6 border-blue-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg text-blue-700">{t('guidedQuestions')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-4">
            {content.guided_questions.map((question, index) => (
              <li
                key={index}
                className="flex items-start gap-3 p-4 bg-blue-50 rounded-lg border border-blue-100"
              >
                <span className="inline-flex items-center justify-center w-7 h-7 bg-blue-600 text-white text-sm font-bold rounded-full flex-shrink-0 mt-0.5">
                  {index + 1}
                </span>
                <div className={mdClass}>
                  <ReactMarkdown>{question}</ReactMarkdown>
                </div>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {/* Section 4 — Annotated Correction (reveal on demand) */}
      <Card className="mb-6 border-green-200">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg text-green-700">{t('annotatedCorrection')}</CardTitle>
            {!correctionVisible && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCorrectionVisible(true)}
                className="min-h-11 border-green-300 text-green-700 hover:bg-green-50"
              >
                {language === 'fr' ? 'Voir la correction' : 'Show correction'}
              </Button>
            )}
          </div>
        </CardHeader>
        {correctionVisible && (
          <CardContent>
            <div className={`${mdClass} bg-green-50 rounded-lg p-4`}>
              <ReactMarkdown>{content.annotated_correction}</ReactMarkdown>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Source Citations */}
      <SourceCitations sources={content.sources_cited} />

      {/* Mark as Complete */}
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
