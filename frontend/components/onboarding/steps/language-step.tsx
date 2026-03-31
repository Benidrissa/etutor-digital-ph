'use client';

import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Check } from 'lucide-react';

interface LanguageStepProps {
  value: string;
  onChange: (value: string) => void;
}

const languages = [
  { code: 'fr', key: 'french', flag: '🇫🇷' },
  { code: 'en', key: 'english', flag: '🇬🇧' },
];

export function LanguageStep({ value, onChange }: LanguageStepProps) {
  const t = useTranslations('Onboarding.step1');

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-2">{t('title')}</h2>
        <p className="text-muted-foreground">{t('description')}</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {languages.map((language) => (
          <Button
            key={language.code}
            variant={value === language.code ? 'default' : 'outline'}
            className="min-h-16 relative flex flex-col items-center justify-center p-4 text-center"
            onClick={() => onChange(language.code)}
          >
            <div className="flex items-center gap-3">
              <span className="text-2xl">{language.flag}</span>
              <span className="font-medium">{t(language.key)}</span>
            </div>
            {value === language.code && (
              <Check className="absolute top-2 right-2 h-4 w-4" />
            )}
          </Button>
        ))}
      </div>
    </div>
  );
}