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
import { Clock, Target, BookOpen, AlertCircle } from 'lucide-react';

interface PlacementTestIntroProps {
  onStartTest: () => void;
  onSkipTest: () => void;
  locale: string;
}

export function PlacementTestIntro({ onStartTest, onSkipTest }: PlacementTestIntroProps) {
  const t = useTranslations('PlacementTest');

  return (
    <div className="space-y-6">
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
                <p className="text-sm text-blue-700">Recommended completion time</p>
              </div>
            </div>

            <div className="flex items-center space-x-3 p-4 bg-green-50 rounded-lg">
              <Target className="h-8 w-8 text-green-600" />
              <div>
                <h3 className="font-semibold text-green-900">{t('numberOfQuestions')}</h3>
                <p className="text-sm text-green-700">Comprehensive assessment</p>
              </div>
            </div>
          </div>

          {/* Domains */}
          <div>
            <h3 className="font-semibold mb-3 flex items-center">
              <BookOpen className="h-5 w-5 mr-2" />
              Assessment Domains
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
            >
              {t('startTest')}
            </Button>
            <Button
              onClick={onSkipTest}
              variant="outline"
              className="flex-1 min-h-12"
              size="lg"
            >
              {t('skipTest')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}