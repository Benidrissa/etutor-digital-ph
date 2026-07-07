'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { AlertTriangle, BookOpenCheck, CheckCircle, Loader2, XCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { SummativeReviewResponse } from '@/lib/api';
import { getSummativeReview } from '@/lib/api';

interface SummativeReviewSectionProps {
  moduleId: string;
  /** Load the review immediately (post-pass results screen) instead of behind a button. */
  autoLoad?: boolean;
}

/**
 * Full corrected review of a summative assessment. The backend only serves it
 * once the learner has PASSED (403 before that), so this component can never
 * expose the answer key to someone still able to retake (#2550).
 */
export function SummativeReviewSection({ moduleId, autoLoad = false }: SummativeReviewSectionProps) {
  const t = useTranslations('SummativeAssessmentResults');

  const [review, setReview] = useState<SummativeReviewResponse | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>(
    autoLoad ? 'loading' : 'idle',
  );

  const fetchReview = useCallback(
    () =>
      getSummativeReview(moduleId)
        .then((data) => {
          setReview(data);
          setStatus('loaded');
        })
        .catch((error) => {
          console.error('Failed to load summative review:', error);
          setStatus('error');
        }),
    [moduleId],
  );

  useEffect(() => {
    if (autoLoad) {
      fetchReview();
    }
  }, [autoLoad, fetchReview]);

  const handleViewReview = () => {
    setStatus('loading');
    fetchReview();
  };

  if (status === 'idle') {
    return (
      <div className="flex justify-center">
        <Button onClick={handleViewReview} variant="outline" className="min-h-11">
          <BookOpenCheck className="w-4 h-4 mr-2" />
          {t('viewReview')}
        </Button>
      </div>
    );
  }

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center gap-2 p-6 text-stone-600">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span>{t('reviewLoading')}</span>
      </div>
    );
  }

  if (status === 'error' || !review) {
    return (
      <Alert className="bg-orange-50 border-orange-200">
        <AlertTriangle className="w-4 h-4" />
        <AlertDescription className="text-orange-800">
          {t('reviewLoadFailed')}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpenCheck className="w-5 h-5" />
          {t('correctedReview')}
        </CardTitle>
        <p className="text-sm text-stone-600">{t('correctedReviewDescription')}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {review.questions.map((questionResult, index) => (
          <Card key={questionResult.question_id} className="border-stone-200">
            <CardContent className="p-4">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-xs">
                    Q{index + 1}
                  </Badge>
                  <div className="flex items-center gap-1">
                    {questionResult.is_correct ? (
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-600" />
                    )}
                    <span className={`text-sm font-medium ${
                      questionResult.is_correct ? 'text-green-700' : 'text-red-700'
                    }`}>
                      {questionResult.is_correct ? t('correct') : t('incorrect')}
                    </span>
                  </div>
                </div>

                <div className="font-medium text-stone-900 leading-relaxed prose prose-sm max-w-none prose-p:my-0">
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                    {questionResult.question}
                  </ReactMarkdown>
                </div>

                <div className="grid md:grid-cols-2 gap-4 text-sm">
                  <div className="space-y-1">
                    <div className="font-medium text-stone-700">{t('yourAnswer')}</div>
                    <div className={`p-3 rounded-lg border ${
                      questionResult.is_correct
                        ? 'bg-green-50 border-green-200 text-green-800'
                        : 'bg-red-50 border-red-200 text-red-800'
                    }`}>
                      {questionResult.options[questionResult.user_answer] ?? t('noAnswer')}
                    </div>
                  </div>

                  {!questionResult.is_correct && (
                    <div className="space-y-1">
                      <div className="font-medium text-stone-700">{t('correctAnswer')}</div>
                      <div className="p-3 rounded-lg border bg-green-50 border-green-200 text-green-800">
                        {questionResult.options[questionResult.correct_answer]}
                      </div>
                    </div>
                  )}
                </div>

                {questionResult.explanation && (
                  <div className="pt-3 border-t border-stone-200">
                    <div className="font-medium text-stone-700 mb-2">{t('explanation')}</div>
                    <div className="text-stone-600 leading-relaxed prose prose-sm max-w-none prose-p:my-0 overflow-x-auto">
                      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                        {questionResult.explanation}
                      </ReactMarkdown>
                    </div>

                    {questionResult.sources_cited.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-stone-100">
                        <div className="text-xs text-stone-500">
                          {questionResult.sources_cited.map((source, idx) => (
                            <div key={idx}>{t('source', { source })}</div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </CardContent>
    </Card>
  );
}
