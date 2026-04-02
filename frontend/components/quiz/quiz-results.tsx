'use client';

import { useTranslations } from 'next-intl';
import { Clock, CheckCircle, XCircle, RotateCcw, ArrowRight, Trophy, Target, BookCheck } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import type { Quiz, QuizAttemptResponse } from '@/lib/api';

interface QuizResultsProps {
  quiz: Quiz;
  result: QuizAttemptResponse;
  onRetry: () => void;
  onContinue: () => void;
}

export function QuizResults({ quiz, result, onRetry, onContinue }: QuizResultsProps) {
  const t = useTranslations('Quiz');
  
  const passingScore = quiz.content.passing_score;
  const scorePercent = result.score;
  const isPassed = result.passed;
  const lessonValidated = result.lesson_validated ?? result.score >= 80;
  
  // Format time spent
  const formatTime = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (minutes > 0) {
      return `${minutes}m ${remainingSeconds}s`;
    }
    return `${seconds}s`;
  };
  
  
  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {/* Header */}
      <div className="text-center space-y-4">
        <div className="mx-auto w-16 h-16 rounded-full flex items-center justify-center mb-4">
          {isPassed ? (
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
              <Trophy className="w-8 h-8 text-green-600" />
            </div>
          ) : (
            <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center">
              <Target className="w-8 h-8 text-amber-600" />
            </div>
          )}
        </div>
        
        <h1 className="text-3xl font-bold text-stone-900">{t('quizComplete')}</h1>
        
        <p className="text-lg text-stone-600">
          {isPassed ? t('congratulations') : t('needsImprovement')}
        </p>
      </div>
      
      {/* Lesson Validation Banner — FR-03.3 */}
      {lessonValidated ? (
        <Card className="bg-teal-50 border-teal-300">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <BookCheck className="w-6 h-6 text-teal-600 flex-shrink-0" />
              <div>
                <p className="font-semibold text-teal-900">{t('lessonCompleted')}</p>
                <p className="text-sm text-teal-700">{t('lessonCompletedDesc')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-amber-50 border-amber-300">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Target className="w-6 h-6 text-amber-600 flex-shrink-0" />
              <div>
                <p className="font-semibold text-amber-900">{t('lessonNotValidated')}</p>
                <p className="text-sm text-amber-700">{t('lessonNotValidatedDesc', { score: 80 })}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
      
      {/* Score Summary Card */}
      <Card className={`${isPassed ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <CardContent className="p-6">
          <div className="text-center space-y-4">
            {/* Final Score */}
            <div className="space-y-2">
              <div className="text-4xl font-bold">
                <span className={isPassed ? 'text-green-700' : 'text-amber-700'}>
                  {scorePercent}%
                </span>
              </div>
              <Badge variant={isPassed ? "default" : "secondary"} className="text-sm px-3 py-1">
                {isPassed ? t('passed') : t('failed')}
              </Badge>
            </div>
            
            {/* Progress Bar */}
            <div className="space-y-2">
              <Progress 
                value={scorePercent} 
                className={`h-3 ${isPassed ? '[&>div]:bg-green-500' : '[&>div]:bg-amber-500'}`}
              />
              <div className="flex justify-between text-sm text-stone-600">
                <span>{t('score')}</span>
                <span>{t('passingScore', { score: passingScore })}</span>
              </div>
            </div>
            
            {/* Key Stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-stone-900">
                  {result.correct_answers}/{result.total_questions}
                </div>
                <div className="text-sm text-stone-600">{t('correctAnswers', { 
                  correct: result.correct_answers, 
                  total: result.total_questions 
                })}</div>
              </div>
              
              <div className="text-center">
                <div className="text-2xl font-bold text-stone-900">
                  {formatTime(result.total_time_seconds)}
                </div>
                <div className="text-sm text-stone-600">{t('timeSpent', { time: formatTime(result.total_time_seconds) })}</div>
              </div>
              
              <div className="text-center">
                <div className="text-2xl font-bold text-stone-900">
                  {quiz.content.questions.length}
                </div>
                <div className="text-sm text-stone-600">{t('totalQuestions')}</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
      
      {/* Detailed Results */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle className="w-5 h-5" />
            {t('questionBreakdown')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {result.results.map((questionResult, index) => {
            const question = quiz.content.questions.find(q => q.id === questionResult.question_id);
            if (!question) return null;
            
            return (
              <Card key={questionResult.question_id} className="border-stone-200">
                <CardContent className="p-4">
                  <div className="space-y-3">
                    {/* Question Header */}
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
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
                          <div className="flex items-center gap-1 text-xs text-stone-500">
                            <Clock className="w-3 h-3" />
                            {t('timeTaken', { seconds: questionResult.time_taken_seconds })}
                          </div>
                        </div>
                        
                        <div className="font-medium text-stone-900 leading-relaxed prose prose-sm max-w-none prose-p:my-0">
                          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                            {question.question}
                          </ReactMarkdown>
                        </div>
                      </div>
                    </div>
                    
                    {/* Answer Comparison */}
                    <div className="grid md:grid-cols-2 gap-4 text-sm">
                      <div className="space-y-1">
                        <div className="font-medium text-stone-700">{t('yourAnswer')}</div>
                        <div className={`p-3 rounded-lg border ${
                          questionResult.is_correct 
                            ? 'bg-green-50 border-green-200 text-green-800'
                            : 'bg-red-50 border-red-200 text-red-800'
                        }`}>
                          {question.options[questionResult.user_answer]}
                        </div>
                      </div>
                      
                      {!questionResult.is_correct && (
                        <div className="space-y-1">
                          <div className="font-medium text-stone-700">{t('correctAnswer')}</div>
                          <div className="p-3 rounded-lg border bg-green-50 border-green-200 text-green-800">
                            {question.options[questionResult.correct_answer]}
                          </div>
                        </div>
                      )}
                    </div>
                    
                    {/* Explanation */}
                    <div className="pt-3 border-t border-stone-200">
                      <div className="font-medium text-stone-700 mb-2">{t('explanation')}</div>
                      <div className="text-stone-600 leading-relaxed prose prose-sm max-w-none prose-p:my-0 overflow-x-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                          {questionResult.explanation}
                        </ReactMarkdown>
                      </div>
                      
                      {/* Sources */}
                      {question.sources_cited.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-stone-100">
                          <div className="text-xs text-stone-500">
                            {question.sources_cited.map((source, idx) => (
                              <div key={idx}>
                                {t('source', { source })}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </CardContent>
      </Card>
      
      {/* Action Buttons — per SRS: no skip; retry regenerates quiz */}
      <div className="flex flex-col sm:flex-row gap-4 justify-center">
        {!lessonValidated && (
          <Button
            variant="outline"
            onClick={onRetry}
            className="min-h-11"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            {t('retryQuiz')}
          </Button>
        )}
        
        {lessonValidated && (
          <Button
            onClick={onContinue}
            className="min-h-11"
          >
            {t('continueToNextUnit')}
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        )}
      </div>
      
      {/* Summary Stats for Screen Readers */}
      <div className="sr-only">
        <p>
          {t('quizCompleteScreenReader', {
            score: result.score,
            correct: result.correct_answers,
            total: result.total_questions,
            time: formatTime(result.total_time_seconds),
            passed: isPassed.toString()
          })}
        </p>
      </div>
    </div>
  );
}