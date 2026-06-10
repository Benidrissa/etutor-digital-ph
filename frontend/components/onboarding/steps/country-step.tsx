'use client';

import { useTranslations } from 'next-intl';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { COUNTRIES } from '@/lib/countries';

interface CountryStepProps {
  value: string;
  onChange: (value: string) => void;
}

export function CountryStep({ value, onChange }: CountryStepProps) {
  const t = useTranslations('Onboarding.step2');
  const tCountries = useTranslations('Countries');

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
            {COUNTRIES.map((country) => (
              <SelectItem key={country.code} value={country.code}>
                <div className="flex items-center gap-2">
                  <span>{country.flag}</span>
                  <span>{tCountries(country.key)}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}