'use client';

import { useTranslations } from 'next-intl';
import { Clock, Trophy, AlertTriangle, Unlock, BarChart3 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { SummativeAssessmentResponse } from '@/lib/api';

interface SummativeAssessmentResultsProps {
  result: SummativeAssessmentResponse;
  onRetry?: () => void;
  onContinue?: () => void;
}

export function SummativeAssessmentResults({ 
  result, 
  onRetry, 
  onContinue 
}: SummativeAssessmentResultsProps) {
  const t = useTranslations('SummativeAssessmentResults');
  
  const formatTime = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };
  
  const formatDate = (isoString: string): string => {
    return new Date(isoString).toLocaleString();
  };
  
  const scorePercentage = (result.score / 100) * 100; // Already in percentage
  const isPass = result.passed;
  const canRetry = result.can_retry && !result.passed;
  
  // Calculate domain breakdown percentages
  const domainBreakdowns = Object.entries(result.domain_breakdown).map(([domain, stats]) => ({
    domain,
    correct: stats.correct,
    total: stats.total,
    percentage: stats.total > 0 ? Math.round((stats.correct / stats.total) * 100) : 0,
  }));
  
  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {/* Header with overall result */}
      <Card className={`${
        isPass 
          ? 'bg-green-50 border-green-200' 
          : 'bg-red-50 border-red-200'
      }`}>
        <CardHeader className="text-center pb-4">
          <div className="flex items-center justify-center mb-4">
            {isPass ? (
              <Trophy className="w-16 h-16 text-green-600" />
            ) : (
              <AlertTriangle className="w-16 h-16 text-red-600" />
            )}
          </div>
          
          <CardTitle className={`text-2xl ${
            isPass ? 'text-green-900' : 'text-red-900'
          }`}>
            {isPass ? t('congratulations') : t('notPassed')}
          </CardTitle>
          
          <div className="space-y-2">
            <div className={`text-4xl font-bold ${
              isPass ? 'text-green-700' : 'text-red-700'
            }`}>
              {result.score}%
            </div>
            <p className={`text-sm ${
              isPass ? 'text-green-800' : 'text-red-800'
            }`}>
              {t('scoreOutOf', { 
                correct: result.correct_answers, 
                total: result.total_questions 
              })}
            </p>
            
            {result.module_unlocked && (
              <div className="flex items-center justify-center gap-2 mt-4 text-green-700">
                <Unlock className="w-5 h-5" />
                <span className="font-medium">{t('moduleUnlocked')}</span>
              </div>
            )}
          </div>
        </CardHeader>
      </Card>
      
      {/* Assessment Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5" />
            {t('assessmentSummary')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl font-bold text-stone-900">
                {result.correct_answers}/{result.total_questions}
              </div>
              <div className="text-sm text-stone-600">{t('correctAnswers')}</div>
            </div>
            
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl font-bold text-stone-900 flex items-center justify-center gap-2">
                <Clock className="w-5 h-5" />
                {formatTime(result.total_time_seconds)}
              </div>
              <div className="text-sm text-stone-600">{t('timeSpent')}</div>
            </div>
            
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl font-bold text-stone-900">
                #{result.attempt_count}
              </div>
              <div className="text-sm text-stone-600">{t('attemptNumber')}</div>
            </div>
          </div>
          
          {/* Score Progress Bar */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm text-stone-600">
              <span>{t('yourScore')}</span>
              <span>{result.score}% ({t('passingScore', { score: 80 })})</span>
            </div>
            <div className="relative">
              <Progress value={scorePercentage} className="h-3" />
              {/* Passing score line */}
              <div 
                className="absolute top-0 bottom-0 w-0.5 bg-stone-400" 
                style={{ left: '80%' }}
              />
            </div>
          </div>
        </CardContent>
      </Card>
      
      {/* Domain Breakdown */}
      {domainBreakdowns.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('domainBreakdown')}</CardTitle>
            <p className="text-sm text-stone-600">
              {t('domainBreakdownDescription')}
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {domainBreakdowns.map(({ domain, correct, total, percentage }) => (
              <div key={domain} className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="font-medium capitalize">{domain}</span>
                  <Badge variant={percentage >= 80 ? "default" : "secondary"}>
                    {correct}/{total} ({percentage}%)
                  </Badge>
                </div>
                <Progress 
                  value={percentage} 
                  className={`h-2 ${
                    percentage >= 80 ? '' : 'opacity-75'
                  }`}
                />
                {percentage < 80 && (
                  <p className="text-xs text-orange-600">
                    {t('reviewRecommended', { domain })}
                  </p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      
      {/* Action Buttons & Next Steps */}
      <div className="space-y-4">
        {!isPass && (
          <Alert className="bg-orange-50 border-orange-200">
            <AlertTriangle className="w-4 h-4" />
            <AlertDescription className="text-orange-800">
              {canRetry ? (
                t('canRetryNow')
              ) : result.next_retry_at ? (
                t('canRetryAfter', { 
                  time: formatDate(result.next_retry_at) 
                })
              ) : (
                t('contactSupport')
              )}
            </AlertDescription>
          </Alert>
        )}
        
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          {canRetry && onRetry && (
            <Button 
              onClick={onRetry}
              variant="outline"
              className="min-h-11"
            >
              {t('retryAssessment')}
            </Button>
          )}
          
          {(isPass && result.module_unlocked) && onContinue && (
            <Button 
              onClick={onContinue}
              className="min-h-11 bg-green-600 hover:bg-green-700"
            >
              <Unlock className="w-4 h-4 mr-2" />
              {t('continueToNextModule')}
            </Button>
          )}
          
          {isPass && !result.module_unlocked && onContinue && (
            <Button 
              onClick={onContinue}
              className="min-h-11"
            >
              {t('backToDashboard')}
            </Button>
          )}
        </div>
      </div>
      
      {/* Assessment Details */}
      <Card className="bg-gray-50">
        <CardContent className="p-4">
          <div className="text-center text-sm text-stone-500 space-y-1">
            <p>{t('attemptedAt')}: {formatDate(result.attempted_at)}</p>
            <p>{t('attemptId')}: {result.attempt_id}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}