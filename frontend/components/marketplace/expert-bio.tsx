'use client';

import { useTranslations, useLocale } from 'next-intl';
import { GraduationCap } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import type { ExpertProfile } from '@/lib/api';

interface ExpertBioProps {
  expert: ExpertProfile;
}

export function ExpertBio({ expert }: ExpertBioProps) {
  const t = useTranslations('Marketplace');
  const locale = useLocale() as 'en' | 'fr';

  const bio = locale === 'fr' ? expert.bio_fr : expert.bio_en;

  return (
    <Card className="border border-stone-200">
      <CardContent className="p-4 flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="shrink-0">
          {expert.avatar_url ? (
            <img
              src={expert.avatar_url}
              alt={expert.name}
              className="h-16 w-16 rounded-full object-cover border-2 border-teal-100"
            />
          ) : (
            <div className="h-16 w-16 rounded-full bg-teal-100 flex items-center justify-center">
              <GraduationCap className="h-8 w-8 text-teal-600" aria-hidden="true" />
            </div>
          )}
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-0">
          <p className="font-semibold text-stone-900 text-base">{expert.name}</p>
          <p className="text-xs text-teal-600 font-medium">
            {t('expertCourses', { count: expert.courses_count })}
          </p>
          {bio && (
            <p className="text-sm text-stone-600 mt-1 leading-relaxed">{bio}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
