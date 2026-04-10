'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useParams, useSearchParams, useRouter, usePathname } from 'next/navigation';
import { GraduationCap, BookOpen, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseCard } from '@/components/learning/course-card';
import { ShareButton } from '@/components/shared/share-button';
import { FilterChips, type FilterSection } from '@/components/learning/filter-chips';
import {
  getCurriculumBySlug,
  getCourses,
  getCourseTaxonomy,
  type CurriculumPublicDetailResponse,
  type CourseResponse,
  type TaxonomyItem,
} from '@/lib/api';
import { setCurriculumContext } from '@/lib/curriculum-context';

export default function CurriculumPage() {
  const t = useTranslations('Curricula');
  const tCourses = useTranslations('Courses');
  const locale = useLocale() as 'fr' | 'en';
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const slug = params.slug as string;

  // Set curriculum context cookie so sidebar/nav stays scoped
  useEffect(() => {
    setCurriculumContext(slug);
  }, [slug]);

  const [curriculum, setCurriculum] = useState<CurriculumPublicDetailResponse | null>(null);
  const [courses, setCourses] = useState<CourseResponse[]>([]);
  const [taxonomy, setTaxonomy] = useState<{
    domains: TaxonomyItem[];
    levels: TaxonomyItem[];
    audience_types: TaxonomyItem[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const activeDomain = searchParams.get('domain');
  const activeLevel = searchParams.get('level');
  const activeAudience = searchParams.get('audience');
  const activeFilterCount =
    (activeDomain ? 1 : 0) + (activeLevel ? 1 : 0) + (activeAudience ? 1 : 0);

  const updateFilter = useCallback(
    (key: string, value: string | null) => {
      const p = new URLSearchParams(searchParams.toString());
      if (value) p.set(key, value);
      else p.delete(key);
      const qs = p.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  const clearFilters = useCallback(() => {
    router.replace(pathname, { scroll: false });
  }, [router, pathname]);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      getCurriculumBySlug(slug),
      getCourseTaxonomy(),
    ])
      .then(([curriculumData, taxonomyData]) => {
        if (!cancelled) {
          setCurriculum(curriculumData);
          setTaxonomy(taxonomyData);
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
  }, [slug]);

  useEffect(() => {
    if (!curriculum) return;
    let cancelled = false;

    getCourses({
      course_domain: activeDomain ?? undefined,
      course_level: activeLevel ?? undefined,
      audience_type: activeAudience ?? undefined,
      curriculum: slug,
    })
      .then((data) => {
        if (!cancelled) {
          setCourses(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [curriculum, slug, activeDomain, activeLevel, activeAudience]);

  const title = curriculum
    ? locale === 'fr'
      ? curriculum.title_fr
      : curriculum.title_en
    : '';
  const description = curriculum
    ? locale === 'fr'
      ? curriculum.description_fr
      : curriculum.description_en
    : undefined;

  const filterSections: FilterSection[] = taxonomy
    ? [
        {
          key: 'domain',
          label: tCourses('domain'),
          items: taxonomy.domains,
        },
        {
          key: 'level',
          label: tCourses('level'),
          items: taxonomy.levels,
        },
        {
          key: 'audience',
          label: tCourses('audience'),
          items: taxonomy.audience_types,
        },
      ]
    : [];

  const activeValues: Record<string, string | null> = {
    domain: activeDomain,
    level: activeLevel,
    audience: activeAudience,
  };

  if (error) {
    return (
      <div className="container mx-auto max-w-6xl px-4 py-16 text-center">
        <p className="text-red-500 text-sm">{t('error')}</p>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      {curriculum && (
        <>
          {/* Curriculum header */}
          <div className="mb-6">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div className="flex items-center gap-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-teal-50 shrink-0">
                  <BookOpen className="h-5 w-5 text-teal-600" />
                </div>
                <div className="min-w-0">
                  <h1 className="text-2xl font-bold text-stone-900 leading-tight">{title}</h1>
                  {description && (
                    <p className="text-stone-600 text-sm mt-1">{description}</p>
                  )}
                </div>
              </div>
              <ShareButton
                url={`/curricula/${slug}`}
                title={title}
                description={description}
                variant="button"
              />
            </div>

            <div className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 border border-teal-200 px-3 py-1 text-xs text-teal-700 font-medium">
              <GraduationCap className="h-3.5 w-3.5" />
              {t('curriculumScope')}
            </div>
          </div>

          {/* Filters (within curriculum scope) */}
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
                    {tCourses('activeFilters', { count: activeFilterCount })}
                  </span>
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 font-medium"
                  >
                    <X className="h-3 w-3" />
                    {tCourses('clearFilters')}
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {loading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-stone-500 text-sm">{t('loading')}</p>
        </div>
      )}

      {!loading && courses.length === 0 && curriculum && (
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <div className="rounded-full bg-teal-50 p-6">
            <GraduationCap className="h-12 w-12 text-teal-600" aria-hidden="true" />
          </div>
          <p className="text-sm text-stone-500">
            {activeFilterCount > 0 ? tCourses('noCoursesMatchFilter') : tCourses('noCourses')}
          </p>
          {activeFilterCount > 0 && (
            <Button variant="outline" size="sm" onClick={clearFilters}>
              {tCourses('clearFilters')}
            </Button>
          )}
        </div>
      )}

      {!loading && courses.length > 0 && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      )}
    </div>
  );
}
