'use client';

import { useEffect, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Link } from '@/i18n/routing';
import { BookOpen, ArrowRight } from 'lucide-react';
import { getCurricula, type CurriculumPublicResponse } from '@/lib/api';

export function CurriculaSection() {
  const t = useTranslations('Dashboard');
  const tC = useTranslations('Curricula');
  const locale = useLocale() as 'fr' | 'en';
  const [curricula, setCurricula] = useState<CurriculumPublicResponse[]>([]);

  useEffect(() => {
    getCurricula()
      .then(setCurricula)
      .catch(() => {});
  }, []);

  if (curricula.length === 0) return null;

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-stone-900">{t('browseCurricula')}</h2>
      </div>
      <p className="text-sm text-stone-500 mb-4">{t('browseCurriculaDesc')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {curricula.slice(0, 4).map((curriculum) => {
          const title = locale === 'fr' ? curriculum.title_fr : curriculum.title_en;
          const desc =
            locale === 'fr' ? curriculum.description_fr : curriculum.description_en;
          return (
            <Link
              key={curriculum.id}
              href={`/curricula/${curriculum.slug}`}
              className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white p-4 hover:border-teal-300 hover:bg-teal-50 transition-colors group min-h-11"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-100 group-hover:bg-teal-200 transition-colors">
                <BookOpen className="h-4 w-4 text-teal-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-stone-900 truncate">{title}</p>
                {desc && (
                  <p className="text-xs text-stone-500 mt-0.5 line-clamp-2">{desc}</p>
                )}
                <p className="text-xs text-teal-600 mt-1">
                  {tC('courseCount', { count: curriculum.course_count })}
                </p>
              </div>
              <ArrowRight className="h-4 w-4 text-stone-400 group-hover:text-teal-600 transition-colors shrink-0 mt-0.5" />
            </Link>
          );
        })}
      </div>
    </div>
  );
}
