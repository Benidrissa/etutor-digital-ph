'use client';

import { useTranslations } from 'next-intl';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface CountryStepProps {
  value: string;
  onChange: (value: string) => void;
}

const countries = [
  'benin',
  'burkina-faso',
  'cabo-verde',
  'cote-divoire',
  'gambia',
  'ghana',
  'guinea',
  'guinea-bissau',
  'liberia',
  'mali',
  'niger',
  'nigeria',
  'senegal',
  'sierra-leone',
  'togo',
  'other-west-african',
  'other'
];

const countryFlags: { [key: string]: string } = {
  'benin': '🇧🇯',
  'burkina-faso': '🇧🇫',
  'cabo-verde': '🇨🇻',
  'cote-divoire': '🇨🇮',
  'gambia': '🇬🇲',
  'ghana': '🇬🇭',
  'guinea': '🇬🇳',
  'guinea-bissau': '🇬🇼',
  'liberia': '🇱🇷',
  'mali': '🇲🇱',
  'niger': '🇳🇪',
  'nigeria': '🇳🇬',
  'senegal': '🇸🇳',
  'sierra-leone': '🇸🇱',
  'togo': '🇹🇬',
  'other-west-african': '🌍',
  'other': '🌐'
};

export function CountryStep({ value, onChange }: CountryStepProps) {
  const t = useTranslations('Onboarding.step2');

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-2">{t('title')}</h2>
        <p className="text-muted-foreground">{t('description')}</p>
      </div>
      
      <div className="max-w-md mx-auto">
        <Select value={value} onValueChange={(value) => value && onChange(value)}>
          <SelectTrigger className="min-h-12">
            <SelectValue placeholder={t('selectCountry')} />
          </SelectTrigger>
          <SelectContent>
            {countries.map((country) => (
              <SelectItem key={country} value={country}>
                <div className="flex items-center gap-2">
                  <span>{countryFlags[country]}</span>
                  <span>{t(`countries.${country}`)}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}