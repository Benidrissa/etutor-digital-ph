'use client';

import { useTranslations } from 'next-intl';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface RoleStepProps {
  value: string;
  onChange: (value: string) => void;
}

const roles = [
  'eleve',
  'etudiant',
  'universitaire',
  'medecin',
  'infirmier',
  'data-analyst',
  'cadre',
  'consultant',
  'commercant',
  'entrepreneur',
  'coach',
  'influencer',
  'autre'
];

const roleIcons: { [key: string]: string } = {
  'eleve': '📚',
  'etudiant': '🎓',
  'universitaire': '🏛️',
  'medecin': '👩‍⚕️',
  'infirmier': '👨‍⚕️',
  'data-analyst': '📊',
  'cadre': '💼',
  'consultant': '🧠',
  'commercant': '🛒',
  'entrepreneur': '🚀',
  'coach': '🏅',
  'influencer': '📱',
  'autre': '👤'
};

export function RoleStep({ value, onChange }: RoleStepProps) {
  const t = useTranslations('Onboarding.step3');

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-2">{t('title')}</h2>
        <p className="text-muted-foreground">{t('description')}</p>
      </div>
      
      <div className="max-w-md mx-auto">
        <Select value={value} onValueChange={(value) => value && onChange(value)}>
          <SelectTrigger className="min-h-12">
            <SelectValue placeholder={t('selectRole')} />
          </SelectTrigger>
          <SelectContent>
            {roles.map((role) => (
              <SelectItem key={role} value={role}>
                <div className="flex items-center gap-2">
                  <span>{roleIcons[role]}</span>
                  <span>{t(`roles.${role}`)}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}