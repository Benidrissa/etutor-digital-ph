'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { Search, SlidersHorizontal } from 'lucide-react';
import {
  getMarketplaceCourses,
  getCourseTaxonomy,
  type MarketplaceCourse,
  type MarketplaceSortOption,
  type MarketplacePriceFilter,
  type TaxonomyItem,
} from '@/lib/api';
import { CourseGrid } from '@/components/marketplace/course-grid';
import { MarketplaceFilters } from '@/components/marketplace/marketplace-filters';

const PAGE_SIZE = 12;

export default function MarketplacePage() {
  const t = useTranslations('Marketplace');
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const locale = (pathname.split('/')[1] || 'fr') as 'fr' | 'en';

  const [courses, setCourses] = useState<MarketplaceCourse[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [taxonomy, setTaxonomy] = useState<{
    domains: TaxonomyItem[];
    levels: TaxonomyItem[];
    audience_types: TaxonomyItem[];
  } | null>(null);

  const activeSearch = searchParams.get('search') ?? '';
  const activeDomain = searchParams.get('domain');
  const activeLevel = searchParams.get('level');
  const activeAudience = searchParams.get('audience');
  const activePrice = (searchParams.get('price') as MarketplacePriceFilter) ?? 'all';
  const activeSort = (searchParams.get('sort') as MarketplaceSortOption) ?? 'newest';
  const activePage = Number(searchParams.get('page') ?? '1');

  const activeFilterCount =
    (activeDomain ? 1 : 0) +
    (activeLevel ? 1 : 0) +
    (activeAudience ? 1 : 0) +
    (activePrice !== 'all' ? 1 : 0);

  const updateParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      params.delete('page');
      router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ''}`, {
        scroll: false,
      });
    },
    [searchParams, router, pathname]
  );

  const clearFilters = useCallback(() => {
    const params = new URLSearchParams();
    if (activeSearch) params.set('search', activeSearch);
    if (activeSort !== 'newest') params.set('sort', activeSort);
    router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ''}`, {
      scroll: false,
    });
  }, [router, pathname, activeSearch, activeSort]);

  useEffect(() => {
    getCourseTaxonomy().then(setTaxonomy).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchCourses() {
      setLoading(true);
      setError(false);
      try {
        const data = await getMarketplaceCourses({
          search: activeSearch || undefined,
          domain: activeDomain ?? undefined,
          level: activeLevel ?? undefined,
          audience: activeAudience ?? undefined,
          price: activePrice !== 'all' ? activePrice : undefined,
          sort: activeSort,
          page: activePage,
          page_size: PAGE_SIZE,
        });
        if (!cancelled) {
          setCourses(data.items);
          setTotalPages(data.total_pages);
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
  }, [activeSearch, activeDomain, activeLevel, activeAudience, activePrice, activeSort, activePage]);

  const handleRetry = () => {
    setError(false);
    setLoading(true);
    getMarketplaceCourses({
      search: activeSearch || undefined,
      domain: activeDomain ?? undefined,
      level: activeLevel ?? undefined,
      audience: activeAudience ?? undefined,
      price: activePrice !== 'all' ? activePrice : undefined,
      sort: activeSort,
      page: activePage,
      page_size: PAGE_SIZE,
    })
      .then((data) => {
        setCourses(data.items);
        setTotalPages(data.total_pages);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  };

  const sortOptions: { value: MarketplaceSortOption; label: string }[] = [
    { value: 'newest', label: t('sortNewest') },
    { value: 'popular', label: t('sortPopular') },
    { value: 'rating', label: t('sortRated') },
    { value: 'price_asc', label: t('sortPriceAsc') },
    { value: 'price_desc', label: t('sortPriceDesc') },
  ];

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 text-center">
        <h1 className="text-3xl font-bold text-stone-900 mb-2">{t('title')}</h1>
        <p className="text-stone-600 text-lg">{t('subtitle')}</p>
      </div>

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-3">
        <div className="relative flex-1">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400"
            aria-hidden="true"
          />
          <input
            type="search"
            value={activeSearch}
            onChange={(e) => updateParam('search', e.target.value || null)}
            placeholder={t('search')}
            className="w-full rounded-lg border border-stone-200 bg-white py-2.5 pl-9 pr-4 text-sm text-stone-900 placeholder:text-stone-400 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 min-h-11"
            aria-label={t('search')}
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className="inline-flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2.5 text-sm font-medium text-stone-700 hover:bg-stone-50 transition-colors min-h-11"
            aria-expanded={showFilters}
            aria-label={t('filters')}
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
            <span>{t('filters')}</span>
            {activeFilterCount > 0 && (
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-teal-600 text-[10px] font-semibold text-white">
                {activeFilterCount}
              </span>
            )}
          </button>

          <select
            value={activeSort}
            onChange={(e) => updateParam('sort', e.target.value)}
            className="rounded-lg border border-stone-200 bg-white py-2.5 pl-3 pr-8 text-sm text-stone-700 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 min-h-11"
            aria-label={t('sortBy')}
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {showFilters && (
        <div className="mb-4">
          <MarketplaceFilters
            taxonomy={taxonomy}
            activeDomain={activeDomain}
            activeLevel={activeLevel}
            activeAudience={activeAudience}
            activePrice={activePrice}
            activeFilterCount={activeFilterCount}
            locale={locale}
            onToggleFilter={updateParam}
            onClearFilters={clearFilters}
          />
        </div>
      )}

      <CourseGrid
        courses={courses}
        loading={loading}
        error={error}
        locale={locale}
        hasActiveFilters={activeFilterCount > 0 || Boolean(activeSearch)}
        onRetry={handleRetry}
        onClearFilters={clearFilters}
      />

      {!loading && !error && totalPages > 1 && (
        <div className="mt-8 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => updateParam('page', activePage > 1 ? String(activePage - 1) : null)}
            disabled={activePage <= 1}
            className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-40 disabled:cursor-not-allowed min-h-11"
            aria-label={t('previous')}
          >
            {t('previous')}
          </button>
          <span className="text-sm text-stone-600">
            {t('page', { current: activePage, total: totalPages })}
          </span>
          <button
            type="button"
            onClick={() =>
              updateParam('page', activePage < totalPages ? String(activePage + 1) : null)
            }
            disabled={activePage >= totalPages}
            className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-40 disabled:cursor-not-allowed min-h-11"
            aria-label={t('next')}
          >
            {t('next')}
          </button>
        </div>
      )}
    </div>
  );
}
