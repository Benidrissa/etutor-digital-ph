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
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Clock, Target, BookOpen, AlertCircle, Calendar, BarChart2 } from 'lucide-react';
import type { PreviousAttempt } from './placement-test-container';

interface PlacementTestIntroProps {
  onStartTest: () => void;
  onSkipTest: () => void;
  locale: string;
  previousAttempt: PreviousAttempt | null;
  loadingPrevious: boolean;
}

const DOMAIN_KEYS = [
  'basic_public_health',
  'epidemiology',
  'biostatistics',
  'data_analysis',
] as const;

export function PlacementTestIntro({
  onStartTest,
  onSkipTest,
  previousAttempt,
  loadingPrevious,
}: PlacementTestIntroProps) {
  const t = useTranslations('PlacementTest');

  const canRetake = !previousAttempt ||
    !previousAttempt.can_retake_after ||
    new Date(previousAttempt.can_retake_after) <= new Date();

  return (
    <div className="space-y-6">
      {/* Previous Result Card */}
      {loadingPrevious ? (
        <Card>
          <CardContent className="flex items-center justify-center py-6">
            <LoadingSpinner className="h-5 w-5" />
          </CardContent>
        </Card>
      ) : previousAttempt ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <BarChart2 className="h-5 w-5 text-primary" />
              {t('previousResult.title')}
            </CardTitle>
            <CardDescription className="flex items-center gap-1">
              <Calendar className="h-4 w-4" />
              {t('previousResult.takenOn', {
                date: new Date(previousAttempt.attempted_at).toLocaleDateString(),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <Badge variant="default" className="text-sm px-3 py-1">
                {t('previousResult.level', { level: previousAttempt.assigned_level })}
              </Badge>
              <Badge variant="secondary" className="text-sm px-3 py-1">
                {t('previousResult.score', {
                  score: Math.round(previousAttempt.score_percentage),
                })}
              </Badge>
            </div>

            {/* Domain breakdown */}
            {Object.keys(previousAttempt.domain_scores).length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-medium">{t('previousResult.domainBreakdown')}</p>
                {DOMAIN_KEYS.map((domain) => {
                  const score = previousAttempt.domain_scores[domain] ?? 0;
                  return (
                    <div key={domain} className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">
                          {t(`previousResult.domains.${domain}`)}
                        </span>
                        <span className="font-medium">{Math.round(score)}%</span>
                      </div>
                      <Progress value={score} className="h-2" />
                    </div>
                  );
                })}
              </div>
            )}

            {!canRetake && previousAttempt.can_retake_after && (
              <div className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 p-3 rounded-lg">
                <Calendar className="h-4 w-4 flex-shrink-0" />
                <span>
                  {t('previousResult.retakeAvailableOn', {
                    date: new Date(previousAttempt.can_retake_after).toLocaleDateString(),
                  })}
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

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

          {/* Skip Warning — only if no previous result */}
          {!previousAttempt && (
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
          )}

          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row gap-3">
            <Button
              onClick={onStartTest}
              disabled={!canRetake}
              className="flex-1 min-h-12 text-lg font-semibold"
              size="lg"
            >
              {previousAttempt ? t('previousResult.retakeNow') : t('startTest')}
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