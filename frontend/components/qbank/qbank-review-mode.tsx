'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import { CheckCircle, XCircle, Clock, ArrowLeft, Filter } from 'lucide-react';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Toggle } from '@/components/ui/toggle';
import type { QBankQuestionResult } from '@/lib/api';

interface QBankReviewModeProps {
  testId: string;
  testTitle: string;
  questions: QBankQuestionResult[];
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes > 0) return `${minutes}m ${remaining}s`;
  return `${seconds}s`;
}

export function QBankReviewMode({ testId, testTitle, questions }: QBankReviewModeProps) {
  const t = useTranslations('QBank');
  const router = useRouter();
  const [showIncorrectOnly, setShowIncorrectOnly] = useState(false);

  const displayed = showIncorrectOnly
    ? questions.filter((q) => !q.is_correct)
    : questions;

  const incorrectCount = questions.filter((q) => !q.is_correct).length;

  return (
    <div className="max-w-2xl mx-auto p-4 space-y-4">
      <div className="flex items-center justify-between gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(`/qbank/tests/${testId}/results`)}
          className="min-h-10 -ml-2"
        >
          <ArrowLeft className="w-4 h-4 mr-1" />
          {t('review.back')}
        </Button>

        <Toggle
          pressed={showIncorrectOnly}
          onPressedChange={setShowIncorrectOnly}
          aria-label={t('review.filterIncorrect')}
          className="min-h-10 gap-2 text-sm"
        >
          <Filter className="w-4 h-4" />
          {t('review.incorrect')}
          {incorrectCount > 0 && (
            <Badge variant="destructive" className="ml-1 text-xs px-1.5 py-0">
              {incorrectCount}
            </Badge>
          )}
        </Toggle>
      </div>

      <div className="space-y-1">
        <h1 className="text-lg font-bold text-stone-900">{testTitle}</h1>
        <p className="text-sm text-stone-500">
          {showIncorrectOnly
            ? t('review.showingIncorrect', { count: incorrectCount })
            : t('review.showingAll', { count: questions.length })}
        </p>
      </div>

      {displayed.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-stone-500">
            {t('review.noIncorrect')}
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {displayed.map((q) => {
          const globalIdx = questions.indexOf(q);
          return (
            <Card
              key={q.question_id}
              className={`border-l-4 ${
                q.is_correct ? 'border-l-green-500' : 'border-l-red-500'
              }`}
            >
              <CardContent className="p-4 space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className="text-xs">
                      {t('review.questionNumber', { n: globalIdx + 1 })}
                    </Badge>
                    {q.category && (
                      <Badge variant="secondary" className="text-xs">
                        {q.category}
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-1 text-xs text-stone-500 shrink-0">
                    <Clock className="w-3 h-3" />
                    {formatTime(q.time_taken_seconds)}
                  </div>
                </div>

                {q.image_url && (
                  <div className="relative w-full aspect-video rounded-md overflow-hidden bg-stone-100">
                    <Image
                      src={q.image_url}
                      alt={t('review.questionImage')}
                      fill
                      className="object-contain"
                    />
                  </div>
                )}

                <p className="text-stone-900 text-sm leading-relaxed">{q.question_text}</p>

                <div className="space-y-2">
                  {q.options.map((option, optIdx) => {
                    const isCorrect = optIdx === q.correct_option_index;
                    const isUserAnswer = optIdx === q.user_answer_index;
                    const isWrongUserAnswer = isUserAnswer && !q.is_correct;

                    let optionClass =
                      'p-3 rounded-lg border text-sm leading-snug';

                    if (isCorrect) {
                      optionClass +=
                        ' bg-green-50 border-green-300 text-green-900 font-medium';
                    } else if (isWrongUserAnswer) {
                      optionClass += ' bg-red-50 border-red-300 text-red-900';
                    } else {
                      optionClass += ' bg-stone-50 border-stone-200 text-stone-600';
                    }

                    return (
                      <div key={optIdx} className={optionClass}>
                        <div className="flex items-start gap-2">
                          <div className="shrink-0 mt-0.5">
                            {isCorrect ? (
                              <CheckCircle className="w-4 h-4 text-green-600" />
                            ) : isWrongUserAnswer ? (
                              <XCircle className="w-4 h-4 text-red-600" />
                            ) : (
                              <span className="w-4 h-4 inline-block" />
                            )}
                          </div>
                          <span>{option}</span>
                          {isUserAnswer && !isCorrect && (
                            <Badge
                              variant="destructive"
                              className="ml-auto text-xs shrink-0"
                            >
                              {t('review.yourAnswer')}
                            </Badge>
                          )}
                          {isCorrect && (
                            <Badge className="ml-auto text-xs shrink-0 bg-green-600">
                              {t('review.correctAnswer')}
                            </Badge>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {q.user_answer_index === null && (
                  <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                    {t('review.notAnswered')}
                  </div>
                )}

                {q.explanation && (
                  <div className="pt-2 border-t border-stone-100">
                    <p className="text-xs font-semibold text-stone-600 mb-1">
                      {t('review.explanation')}
                    </p>
                    <p className="text-sm text-stone-700 leading-relaxed">{q.explanation}</p>
                  </div>
                )}

                {q.sources_cited.length > 0 && (
                  <div className="text-xs text-stone-400 space-y-0.5">
                    {q.sources_cited.map((src, sIdx) => (
                      <div key={sIdx}>{t('review.source', { source: src })}</div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {displayed.length > 0 && (
        <div className="pb-4">
          <Button
            variant="outline"
            className="w-full min-h-11"
            onClick={() => router.push(`/qbank/tests/${testId}/results`)}
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            {t('review.backToResults')}
          </Button>
        </div>
      )}
    </div>
  );
}
