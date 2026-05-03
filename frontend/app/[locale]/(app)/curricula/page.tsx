'use client';

import { useEffect, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Link } from '@/i18n/routing';
import { ArrowRight, BookOpen, GraduationCap } from 'lucide-react';
import { getCurricula, type CurriculumPublicResponse } from '@/lib/api';

export default function CurriculaIndexPage() {
  const t = useTranslations('Curricula');
  const locale = useLocale() as 'fr' | 'en';
  const [curricula, setCurricula] = useState<CurriculumPublicResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCurricula()
      .then((data) => {
        if (!cancelled) setCurricula(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-8 flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-teal-100">
          <GraduationCap className="h-6 w-6 text-teal-600" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-stone-900">{t('pageTitle')}</h1>
          <p className="text-stone-600 text-lg mt-1">{t('pageDescription')}</p>
        </div>
      </div>

      {loading && (
        <p className="text-sm text-stone-500" role="status" aria-live="polite">
          {t('loading')}
        </p>
      )}

      {!loading && error && (
        <p className="text-sm text-red-600" role="alert">
          {t('error')}
        </p>
      )}

      {!loading && !error && curricula.length === 0 && (
        <div className="rounded-xl border border-dashed border-stone-300 bg-stone-50 p-8 text-center">
          <p className="text-sm text-stone-600">{t('noCurricula')}</p>
        </div>
      )}

      {!loading && !error && curricula.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {curricula.map((c) => {
            const title = locale === 'fr' ? c.title_fr : c.title_en;
            const desc = locale === 'fr' ? c.description_fr : c.description_en;
            return (
              <li key={c.id}>
                <Link
                  href={`/curricula/${c.slug}`}
                  className="group flex h-full flex-col gap-3 rounded-xl border border-stone-200 bg-white p-5 transition-colors hover:border-teal-300 hover:bg-teal-50 min-h-11"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-100 group-hover:bg-teal-200 transition-colors">
                      <BookOpen className="h-5 w-5 text-teal-600" />
                    </div>
                    <ArrowRight className="h-4 w-4 text-stone-400 group-hover:text-teal-600 transition-colors mt-1" />
                  </div>
                  <h2 className="text-base font-semibold text-stone-900 line-clamp-2">{title}</h2>
                  {desc && (
                    <p className="text-sm text-stone-500 line-clamp-3 flex-1">{desc}</p>
                  )}
                  <p className="text-xs text-teal-700 font-medium">
                    {t('courseCount', { count: c.course_count })}
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
