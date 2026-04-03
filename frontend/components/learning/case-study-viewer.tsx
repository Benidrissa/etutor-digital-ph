'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Clock, FileText, RefreshCw, Loader2, AlertTriangle, WifiOff } from 'lucide-react';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { LessonSkeleton } from './lesson-skeleton';
import { SourceCitations } from './source-citations';
import { apiFetch } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import {
  getContentFromDB,
  saveContentToDB,
  queueOfflineAction,
  isOnline,
} from '@/lib/offline/content-loader';

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

interface GeneratingResponse {
  status: 'generating';
  task_id: string;
  message: string;
}

interface CaseStudyViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
  countryContext?: string;
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
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCompleted, setIsCompleted] = useState(false);
  const [correctionVisible, setCorrectionVisible] = useState(false);
  const [forceRegenerate, setForceRegenerate] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [servedFromCache, setServedFromCache] = useState(false);
  const [offlineUnavailable, setOfflineUnavailable] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartRef = useRef<number>(0);

  const currentUser = useCurrentUser();
  const country = countryContext || currentUser?.country || 'SN';

  const t = useTranslations('CaseStudyViewer');

  const pollStatus = (taskId: string, startTime: number) => {
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
          const caseRes = await apiFetch<CaseStudyData>(
            `/api/v1/content/cases/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}`
          );
          setCaseStudyData(caseRes);
          setIsGenerating(false);
          setIsLoading(false);
          setIsRefreshing(false);
          setForceRegenerate(false);
        } else if (statusRes.status === 'failed') {
          setError(t('generationFailed'));
          setIsGenerating(false);
          setIsLoading(false);
          setIsRefreshing(false);
        } else {
          pollStatus(taskId, startTime);
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

        if (!forceRegenerate) {
          const cached = await getContentFromDB<CaseStudyData>('case_studies', cacheKey);
          if (cached) {
            setCaseStudyData(cached);
            setServedFromCache(true);
            setIsLoading(false);
            return;
          }
        }

        if (!isOnline()) {
          setOfflineUnavailable(true);
          setIsLoading(false);
          return;
        }

        const forceParam = forceRegenerate ? '&force_regenerate=true' : '';
        const res = await apiFetch<CaseStudyData | GeneratingResponse>(
          `/api/v1/content/cases/${moduleId}/${unitId}?language=${language}&level=${level}&country=${country}${forceParam}`
        );

        if ('status' in res && res.status === 'generating') {
          setIsLoading(false);
          setIsGenerating(true);
          pollStartRef.current = Date.now();
          pollStatus((res as GeneratingResponse).task_id, pollStartRef.current);
        } else {
          const caseStudy = res as CaseStudyData;
          setCaseStudyData(caseStudy);
          setServedFromCache(false);
          setIsLoading(false);
          setIsRefreshing(false);
          setForceRegenerate(false);
          await saveContentToDB('case_studies', { ...caseStudy, id: cacheKey });
        }
      } catch {
        setError(t('loadError'));
        setIsLoading(false);
        setIsRefreshing(false);
      }
    };

    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, unitId, language, level, country, forceRegenerate]);

  const handleRefresh = () => {
    setCaseStudyData(null);
    setIsRefreshing(true);
    setForceRegenerate(true);
  };

  const handleMarkComplete = async () => {
    try {
      if (!isOnline()) {
        await queueOfflineAction({
          type: 'case_study_complete',
          payload: { module_id: moduleId, unit_id: unitId },
        });
        setIsCompleted(true);
        onComplete?.();
        return;
      }
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
    pre: ({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) => (
      <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 overflow-x-auto text-sm font-mono whitespace-pre leading-relaxed" {...props}>{children}</pre>
    ),
    code: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
      <code className="bg-gray-100 rounded px-1.5 py-0.5 text-sm font-mono" {...props}>{children}</code>
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
              onClick={() => { setError(null); setCaseStudyData(null); setForceRegenerate(false); setIsLoading(false); setIsGenerating(false); }}
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
            <div className="text-gray-800 font-medium mb-2">{t('offlineUnavailableTitle')}</div>
            <p className="text-gray-600">{t('offlineUnavailable')}</p>
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

  if (isLoading && !caseStudyData) {
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
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
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
            {servedFromCache && (
              <Badge variant="secondary" className="flex items-center gap-1">
                <WifiOff className="w-3 h-3" />
                {t('offlineBadge')}
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

      {/* Section 1 — AOF Context */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg text-teal-700">{t('aofContext')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className={mdClass}>
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.aof_context}</ReactMarkdown>
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
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.real_data}</ReactMarkdown>
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
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{question}</ReactMarkdown>
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
                {t('showCorrection')}
              </Button>
            )}
          </div>
        </CardHeader>
        {correctionVisible && (
          <CardContent>
            <div className={`${mdClass} bg-green-50 rounded-lg p-4`}>
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={mdComponents}>{content.annotated_correction}</ReactMarkdown>
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
          disabled={isCompleted || isLoading || isGenerating}
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
