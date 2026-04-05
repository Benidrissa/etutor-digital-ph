'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { AlertCircle } from 'lucide-react';
import { LanguageStep } from './steps/language-step';
import { CountryStep } from './steps/country-step';
import { RoleStep } from './steps/role-step';
import { LevelStep } from './steps/level-step';
import { useOnboarding } from '@/lib/hooks/use-onboarding';
import { apiFetch } from '@/lib/api';

interface OnboardingData {
  language: string;
  country: string;
  role: string;
  level: number;
}

interface PreassessmentStatus {
  preassessment_enabled: boolean;
  preassessment_mandatory: boolean;
  completed: boolean;
  course_id: string;
  course_slug: string;
  course_title_fr?: string;
  course_title_en?: string;
}

const TOTAL_STEPS = 4;

export function OnboardingFlow() {
  const t = useTranslations('Onboarding');
  const tPlacement = useTranslations('PlacementTest');
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [data, setData] = useState<OnboardingData>({
    language: 'fr',
    country: '',
    role: '',
    level: 1,
  });
  const [showChoice, setShowChoice] = useState(false);
  const [pendingCourseSlug, setPendingCourseSlug] = useState<string | null>(null);
  const [pendingCourseName, setPendingCourseName] = useState<string | null>(null);

  const locale = useLocale();
  const { completeOnboarding, isLoading, error } = useOnboarding();

  const updateData = (key: keyof OnboardingData, value: string | number) => {
    setData(prev => ({ ...prev, [key]: value }));
  };

  const handleNext = () => {
    if (currentStep < TOTAL_STEPS) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handlePrevious = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const canProceed = () => {
    switch (currentStep) {
      case 1:
        return data.language !== '';
      case 2:
        return data.country !== '';
      case 3:
        return data.role !== '';
      case 4:
        return data.level > 0;
      default:
        return false;
    }
  };

  const handleComplete = async () => {
    try {
      await completeOnboarding({
        preferred_language: data.language,
        country: data.country,
        professional_role: data.role,
        current_level: data.level,
      });

      // Check if the enrolled course has a pre-assessment
      try {
        const status = await apiFetch<PreassessmentStatus>('/api/v1/users/me/enrolled-course/preassessment/status');

        if (status.preassessment_enabled && !status.completed) {
          if (status.preassessment_mandatory) {
            router.push(`/courses/${status.course_slug}/placement-test`);
          } else {
            setPendingCourseSlug(status.course_slug);
            const title = locale === 'fr'
              ? (status.course_title_fr ?? status.course_slug)
              : (status.course_title_en ?? status.course_slug);
            setPendingCourseName(title);
            setShowChoice(true);
          }
        } else {
          router.push('/courses');
        }
      } catch {
        router.push('/courses');
      }
    } catch (err) {
      console.error('Onboarding completion failed:', err);
    }
  };

  const progressPercent = (currentStep / TOTAL_STEPS) * 100;

  if (showChoice && pendingCourseSlug) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-2xl">
        <Card>
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">{tPlacement('courseSpecific.choiceTitle')}</CardTitle>
            <CardDescription>
              {tPlacement('courseSpecific.choiceDescription', { courseName: pendingCourseName ?? pendingCourseSlug })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="flex items-start space-x-3">
                <AlertCircle className="h-5 w-5 text-amber-600 mt-0.5" />
                <p className="text-sm text-amber-800">
                  {tPlacement('courseSpecific.optional')}
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-3">
              <Button
                onClick={() => router.push(`/courses/${pendingCourseSlug}/placement-test`)}
                className="w-full min-h-12 text-lg font-semibold"
                size="lg"
              >
                {tPlacement('courseSpecific.startAssessment')}
              </Button>
              <Button
                onClick={() => router.push('/dashboard')}
                variant="outline"
                className="w-full min-h-12"
                size="lg"
              >
                {tPlacement('courseSpecific.skipToLevel1')}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground text-center">
              {tPlacement('courseSpecific.skipChoiceWarning')}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{t('welcome')}</CardTitle>
          <CardDescription>{t('subtitle')}</CardDescription>
          <div className="mt-4">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm font-medium">
                {t('step', { current: currentStep, total: TOTAL_STEPS })}
              </span>
              <span className="text-sm text-muted-foreground">
                {Math.round(progressPercent)}%
              </span>
            </div>
            <Progress value={progressPercent} className="h-2" />
          </div>
        </CardHeader>
        
        <CardContent className="space-y-6">
          {currentStep === 1 && (
            <LanguageStep
              value={data.language}
              onChange={(value) => updateData('language', value)}
            />
          )}
          
          {currentStep === 2 && (
            <CountryStep
              value={data.country}
              onChange={(value) => updateData('country', value)}
            />
          )}
          
          {currentStep === 3 && (
            <RoleStep
              value={data.role}
              onChange={(value) => updateData('role', value)}
            />
          )}
          
          {currentStep === 4 && (
            <LevelStep
              value={data.level}
              onChange={(value) => updateData('level', value)}
            />
          )}

          {error && (
            <div className="text-sm text-red-600 bg-red-50 p-3 rounded-md">
              {t('error')}
            </div>
          )}
          
          <div className="flex justify-between pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={handlePrevious}
              disabled={currentStep === 1}
              className="min-h-11"
            >
              {t('previous')}
            </Button>
            
            {currentStep < TOTAL_STEPS ? (
              <Button
                type="button"
                onClick={handleNext}
                disabled={!canProceed()}
                className="min-h-11"
              >
                {t('next')}
              </Button>
            ) : (
              <Button
                type="button"
                onClick={handleComplete}
                disabled={!canProceed() || isLoading}
                className="min-h-11"
              >
                {isLoading ? t('completing') : t('complete')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
