'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter, usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { LanguageStep } from './steps/language-step';
import { CountryStep } from './steps/country-step';
import { RoleStep } from './steps/role-step';
import { LevelStep } from './steps/level-step';
import { useOnboarding } from '@/lib/hooks/use-onboarding';

interface OnboardingData {
  language: string;
  country: string;
  role: string;
  level: number;
}

const TOTAL_STEPS = 4;

export function OnboardingFlow() {
  const t = useTranslations('Onboarding');
  const router = useRouter();
  const pathname = usePathname();
  const locale = pathname.split('/')[1]; // Extract locale from path
  const [currentStep, setCurrentStep] = useState(1);
  const [data, setData] = useState<OnboardingData>({
    language: 'fr',
    country: '',
    role: '',
    level: 1,
  });

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
      
      // Redirect to diagnostic assessment
      router.push(`/${locale}/placement-test`);
    } catch (err) {
      console.error('Onboarding completion failed:', err);
    }
  };

  const progressPercent = (currentStep / TOTAL_STEPS) * 100;

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