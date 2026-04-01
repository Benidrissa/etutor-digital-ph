'use client';

import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Clock, Target, BookOpen, AlertCircle, CheckCircle } from 'lucide-react';
import type { PreviousAttempt } from './placement-test-container';

interface PlacementTestIntroProps {
  onStartTest: () => void;
  onSkipTest: () => void;
  locale: string;
  previousAttempt: PreviousAttempt | null;
  loadingPrevious: boolean;
}

const DOMAIN_ORDER = ['level_1', 'level_2', 'level_3', 'level_4'] as const;

export function PlacementTestIntro({
  onStartTest,
  onSkipTest,
  previousAttempt,
  loadingPrevious,
}: PlacementTestIntroProps) {
  const t = useTranslations('PlacementTest');

  const canRetake =
    !previousAttempt?.can_retake_after ||
    new Date(previousAttempt.can_retake_after) <= new Date();

  return (
    <div className="space-y-6">
      {/* Previous result card */}
      {!loadingPrevious && previousAttempt && (
        <Card className="border-green-200 bg-green-50">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-green-900">
              <CheckCircle className="h-5 w-5 text-green-600" />
              {t('previousResult.title')}
            </CardTitle>
            <CardDescription className="text-green-700">
              {t('previousResult.takenOn', {
                date: new Date(previousAttempt.attempted_at).toLocaleDateString(),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <Badge className="bg-green-700 text-white">
                {t('previousResult.assignedLevel', { level: previousAttempt.assigned_level })}
              </Badge>
              <Badge variant="outline" className="border-green-600 text-green-800">
                {t('previousResult.score', {
                  score: Math.round(previousAttempt.adjusted_score),
                })}
              </Badge>
            </div>

            {Object.keys(previousAttempt.domain_scores).length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium text-green-900">
                  {t('previousResult.domainBreakdown')}
                </p>
                {DOMAIN_ORDER.map((key) => {
                  const score = previousAttempt.domain_scores[key];
                  if (score === undefined) return null;
                  return (
                    <div key={key} className="space-y-1">
                      <div className="flex justify-between text-xs text-green-800">
                        <span>{t(`previousResult.domains.${key}`)}</span>
                        <span>{Math.round(score)}%</span>
                      </div>
                      <Progress value={score} className="h-2" />
                    </div>
                  );
                })}
              </div>
            )}

            {!canRetake && previousAttempt.can_retake_after && (
              <p className="text-xs text-amber-700">
                {t('previousResult.canRetakeOn', {
                  date: new Date(previousAttempt.can_retake_after).toLocaleDateString(),
                })}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-3xl font-bold">{t('title')}</CardTitle>
          <CardDescription className="text-lg">
            {t('description')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="text-center">
            <p className="text-muted-foreground">
              {t('instructions')}
            </p>
          </div>

          {/* Test Overview */}
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center space-x-3 p-4 bg-blue-50 rounded-lg">
              <Clock className="h-8 w-8 text-blue-600" />
              <div>
                <h3 className="font-semibold text-blue-900">{t('timeLimit')}</h3>
                <p className="text-sm text-blue-700">{t('timeLimitSubtext')}</p>
              </div>
            </div>

            <div className="flex items-center space-x-3 p-4 bg-green-50 rounded-lg">
              <Target className="h-8 w-8 text-green-600" />
              <div>
                <h3 className="font-semibold text-green-900">{t('numberOfQuestions')}</h3>
                <p className="text-sm text-green-700">{t('numberOfQuestionsSubtext')}</p>
              </div>
            </div>
          </div>

          {/* Domains */}
          <div>
            <h3 className="font-semibold mb-3 flex items-center">
              <BookOpen className="h-5 w-5 mr-2" />
              {t('assessmentDomains')}
            </h3>
            <div className="grid gap-2 md:grid-cols-2">
              <Badge variant="outline" className="justify-start p-3">
                {t('domains.foundations')}
              </Badge>
              <Badge variant="outline" className="justify-start p-3">
                {t('domains.epidemiology')}
              </Badge>
              <Badge variant="outline" className="justify-start p-3">
                {t('domains.biostatistics')}
              </Badge>
              <Badge variant="outline" className="justify-start p-3">
                {t('domains.healthSystems')}
              </Badge>
            </div>
          </div>

          {/* Skip Warning */}
          <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="flex items-start space-x-3">
              <AlertCircle className="h-5 w-5 text-amber-600 mt-0.5" />
              <div>
                <p className="text-sm text-amber-800">
                  {t('skipWarning')}
                </p>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row gap-3">
            <Button
              onClick={onStartTest}
              className="flex-1 min-h-12 text-lg font-semibold"
              size="lg"
              disabled={!canRetake}
            >
              {previousAttempt
                ? t('previousResult.retakeNow')
                : t('startTest')}
            </Button>
            {!previousAttempt && (
              <Button
                onClick={onSkipTest}
                variant="outline"
                className="flex-1 min-h-12"
                size="lg"
              >
                {t('skipTest')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
