'use client';

import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Check } from 'lucide-react';

interface LevelStepProps {
  value: number;
  onChange: (value: number) => void;
}

const levels = [
  { level: 1, key: 'debutant', icon: '🟢' },
  { level: 2, key: 'intermediaire', icon: '🟡' },
  { level: 3, key: 'avance', icon: '🔴' }
];

export function LevelStep({ value, onChange }: LevelStepProps) {
  const t = useTranslations('Onboarding.step4');

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-2">{t('title')}</h2>
        <p className="text-muted-foreground">{t('description')}</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {levels.map((levelOption) => (
          <Button
            key={levelOption.level}
            variant={value === levelOption.level ? 'default' : 'outline'}
            className="min-h-16 relative flex flex-col items-center justify-center p-4 text-center"
            onClick={() => onChange(levelOption.level)}
          >
            <div className="flex flex-col items-center gap-2">
              <span className="text-2xl">{levelOption.icon}</span>
              <span className="font-medium text-sm">
                {t(`levels.${levelOption.key}`)}
              </span>
            </div>
            {value === levelOption.level && (
              <Check className="absolute top-2 right-2 h-4 w-4" />
            )}
          </Button>
        ))}
      </div>
    </div>
  );
}