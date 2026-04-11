'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { GraduationCap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseCard } from '@/components/learning/course-card';
import { CourseFilterBar } from '@/components/learning/course-filter-bar';
import { type FilterSection } from '@/components/learning/filter-chips';
import {
  getCourses,
  getCourseTaxonomy,
  type CourseResponse,
  type TaxonomyItem,
} from '@/lib/api';
import { clearCurriculumContext } from '@/lib/curriculum-context';

export default function CoursesPage() {
  const t = useTranslations('Courses');
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const locale = (pathname.split('/')[1] || 'fr') as 'fr' | 'en';

  useEffect(() => {
    clearCurriculumContext();
  }, []);

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
  const activeSearch = searchParams.get('search');

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

    async function fetchCourses() {
      setLoading(true);
      setError(false);
      try {
        const data = await getCourses({
          course_domain: activeDomain ?? undefined,
          course_level: activeLevel ?? undefined,
          audience_type: activeAudience ?? undefined,
          search: activeSearch ?? undefined,
        });
        if (!cancelled) {
          setCourses(data);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      }
    }

    fetchCourses();
    return () => {
      cancelled = true;
    };
  }, [activeDomain, activeLevel, activeAudience, activeSearch]);

  const handleRetry = () => {
    setError(false);
    setLoading(true);
    getCourses({
      course_domain: activeDomain ?? undefined,
      course_level: activeLevel ?? undefined,
      audience_type: activeAudience ?? undefined,
      search: activeSearch ?? undefined,
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
          items: taxonomy.domains,
        },
        {
          key: 'level',
          label: t('level'),
          items: taxonomy.levels,
        },
        {
          key: 'audience',
          label: t('audience'),
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
        <CourseFilterBar
          filterSections={filterSections}
          activeValues={activeValues}
          activeSearch={activeSearch}
          courseCount={courses.length}
          loading={loading}
          locale={locale}
          onUpdateFilter={updateFilter}
          onClearFilters={clearFilters}
        />
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
            {activeValues.domain || activeValues.level || activeValues.audience || activeSearch
              ? t('noCoursesMatchFilter')
              : t('noCourses')}
          </h2>
          <p className="text-stone-500 text-sm max-w-sm">
            {activeValues.domain || activeValues.level || activeValues.audience || activeSearch ? (
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
