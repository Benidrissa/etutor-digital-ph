import { getTranslations } from 'next-intl/server';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link } from '@/i18n/routing';

interface NavUnit {
  unit_number: string;
  title_fr: string;
  title_en: string;
}

interface UnitNavProps {
  moduleId: string;
  prev: NavUnit | null;
  next: NavUnit | null;
  language: 'fr' | 'en';
}

export async function UnitNav({ moduleId, prev, next, language }: UnitNavProps) {
  if (!prev && !next) return null;

  const t = await getTranslations('UnitPage');

  const prevTitle = prev ? (language === 'fr' ? prev.title_fr : prev.title_en) : '';
  const nextTitle = next ? (language === 'fr' ? next.title_fr : next.title_en) : '';

  const linkClass =
    'flex-1 sm:flex-none min-h-11 inline-flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-4 py-2 text-stone-700 hover:bg-stone-50 hover:border-stone-300 transition-colors max-w-full sm:max-w-[45%]';

  return (
    <nav className="mt-8 flex items-center justify-between gap-3">
      {prev ? (
        <Link
          href={`/modules/${moduleId}/units/${prev.unit_number}`}
          className={linkClass}
        >
          <ChevronLeft className="w-4 h-4 shrink-0" />
          <span className="flex flex-col items-start min-w-0">
            <span className="text-xs text-stone-500">{t('previous')}</span>
            <span className="hidden sm:block text-sm font-medium truncate max-w-full">
              {prevTitle}
            </span>
          </span>
        </Link>
      ) : (
        <div />
      )}

      {next ? (
        <Link
          href={`/modules/${moduleId}/units/${next.unit_number}`}
          className={`${linkClass} justify-end text-right ml-auto`}
        >
          <span className="flex flex-col items-end min-w-0">
            <span className="text-xs text-stone-500">{t('next')}</span>
            <span className="hidden sm:block text-sm font-medium truncate max-w-full">
              {nextTitle}
            </span>
          </span>
          <ChevronRight className="w-4 h-4 shrink-0" />
        </Link>
      ) : (
        <div />
      )}
    </nav>
  );
}
