'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { GraduationCap, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseCard } from '@/components/learning/course-card';
import {
  getCourses,
  getCourseTaxonomy,
  type CourseResponse,
  type TaxonomyItem,
} from '@/lib/api';

interface FilterSection {
  key: string;
  label: string;
  allLabel: string;
  items: TaxonomyItem[];
}

function FilterChips({
  section,
  active,
  locale,
  onToggle,
}: {
  section: FilterSection;
  active: string | null;
  locale: 'fr' | 'en';
  onToggle: (key: string, value: string | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-stone-500 uppercase tracking-wide">
        {section.label}
      </span>
      <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
        <button
          type="button"
          onClick={() => onToggle(section.key, null)}
          className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors min-h-[36px] ${
            !active
              ? 'bg-teal-600 text-white'
              : 'bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200'
          }`}
        >
          {section.allLabel}
        </button>
        {section.items.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() =>
              onToggle(section.key, active === item.value ? null : item.value)
            }
            className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors min-h-[36px] ${
              active === item.value
                ? 'bg-teal-600 text-white'
                : 'bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200'
            }`}
          >
            {locale === 'fr' ? item.label_fr : item.label_en}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function CoursesPage() {
  const t = useTranslations('Courses');
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const locale = (pathname.split('/')[1] || 'fr') as 'fr' | 'en';

  const [courses, setCourses] = useState<CourseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [taxonomy, setTaxonomy] = useState<{
    domains: TaxonomyItem[];
    levels: TaxonomyItem[];
    audience_types: TaxonomyItem[];
  } | null>(null);

  // Read filters from URL
  const activeDomain = searchParams.get('domain');
  const activeLevel = searchParams.get('level');
  const activeAudience = searchParams.get('audience');
  const activeFilterCount =
    (activeDomain ? 1 : 0) + (activeLevel ? 1 : 0) + (activeAudience ? 1 : 0);

  const updateFilter = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      const qs = params.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  const clearFilters = useCallback(() => {
    router.replace(pathname, { scroll: false });
  }, [router, pathname]);

  // Load taxonomy once
  useEffect(() => {
    getCourseTaxonomy()
      .then(setTaxonomy)
      .catch(() => {});
  }, []);

  // Load courses when filters change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    getCourses({
      course_domain: activeDomain ?? undefined,
      course_level: activeLevel ?? undefined,
      audience_type: activeAudience ?? undefined,
    })
      .then((data) => {
        if (!cancelled) {
          setCourses(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeDomain, activeLevel, activeAudience]);

  const handleRetry = () => {
    setError(false);
    setLoading(true);
    getCourses({
      course_domain: activeDomain ?? undefined,
      course_level: activeLevel ?? undefined,
      audience_type: activeAudience ?? undefined,
    })
      .then((data) => {
        setCourses(data);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  };

  const filterSections: FilterSection[] = taxonomy
    ? [
        {
          key: 'domain',
          label: t('domain'),
          allLabel: t('allDomains'),
          items: taxonomy.domains,
        },
        {
          key: 'level',
          label: t('level'),
          allLabel: t('allLevels'),
          items: taxonomy.levels,
        },
        {
          key: 'audience',
          label: t('audience'),
          allLabel: t('allAudiences'),
          items: taxonomy.audience_types,
        },
      ]
    : [];

  const activeValues: Record<string, string | null> = {
    domain: activeDomain,
    level: activeLevel,
    audience: activeAudience,
  };

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 text-center">
        <h1 className="text-3xl font-bold text-stone-900 mb-2">{t('title')}</h1>
        <p className="text-stone-600 text-lg">{t('subtitle')}</p>
      </div>

      {/* Filter bar */}
      {taxonomy && (
        <div className="mb-6 space-y-3 bg-stone-50 rounded-xl p-4 border border-stone-200">
          {filterSections.map((section) => (
            <FilterChips
              key={section.key}
              section={section}
              active={activeValues[section.key]}
              locale={locale}
              onToggle={updateFilter}
            />
          ))}
          {activeFilterCount > 0 && (
            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-stone-500">
                {t('activeFilters', { count: activeFilterCount })}
              </span>
              <button
                type="button"
                onClick={clearFilters}
                className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 font-medium"
              >
                <X className="h-3 w-3" />
                {t('clearFilters')}
              </button>
            </div>
          )}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-stone-500 text-sm">{t('loading')}</p>
        </div>
      )}

      {error && (
        <div className="flex flex-col items-center justify-center py-12 gap-4">
          <p className="text-red-500 text-sm">{t('error')}</p>
          <Button variant="outline" size="sm" onClick={handleRetry}>
            {t('tryAgain')}
          </Button>
        </div>
      )}

      {!loading && !error && courses.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <div className="rounded-full bg-teal-50 p-6">
            <GraduationCap className="h-12 w-12 text-teal-600" aria-hidden="true" />
          </div>
          <h2 className="text-lg font-semibold text-stone-900">
            {activeFilterCount > 0 ? t('noCoursesMatchFilter') : t('noCourses')}
          </h2>
          <p className="text-stone-500 text-sm max-w-sm">
            {activeFilterCount > 0 ? (
              <button
                type="button"
                onClick={clearFilters}
                className="text-teal-600 hover:underline font-medium"
              >
                {t('clearFilters')}
              </button>
            ) : (
              t('noCoursesDescription')
            )}
          </p>
        </div>
      )}

      {!loading && !error && courses.length > 0 && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      )}
    </div>
  );
}
