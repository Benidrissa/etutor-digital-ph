'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Search, X, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { FilterChips, type FilterSection } from './filter-chips';
import { useDebounce } from '@/lib/hooks/use-debounce';

interface CourseFilterBarProps {
  filterSections: FilterSection[];
  activeValues: Record<string, string | null>;
  activeSearch: string | null;
  courseCount: number;
  loading: boolean;
  locale: 'fr' | 'en';
  onUpdateFilter: (key: string, value: string | null) => void;
  onClearFilters: () => void;
}

export function CourseFilterBar({
  filterSections,
  activeValues,
  activeSearch,
  courseCount,
  loading,
  locale,
  onUpdateFilter,
  onClearFilters,
}: CourseFilterBarProps) {
  const t = useTranslations('Courses');
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  // Use activeSearch as key to reset input when URL clears (e.g. clearFilters)
  const searchKey = activeSearch ?? '';
  const [searchInput, setSearchInput] = useState(searchKey);
  const debouncedSearch = useDebounce(searchInput, 300);

  // Reset local input when activeSearch is cleared externally (e.g. clearFilters)
  const [prevSearchKey, setPrevSearchKey] = useState(searchKey);
  if (searchKey !== prevSearchKey) {
    setPrevSearchKey(searchKey);
    if (searchKey === '' && searchInput !== '') {
      setSearchInput('');
    }
  }

  // Sync debounced search to URL
  useEffect(() => {
    const current = activeSearch ?? '';
    if (debouncedSearch !== current) {
      onUpdateFilter('search', debouncedSearch || null);
    }
  }, [debouncedSearch]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeFilterCount = Object.values(activeValues).filter(Boolean).length;
  const totalActiveCount = activeFilterCount + (activeSearch ? 1 : 0);

  // Build active filter labels for collapsed mobile badges
  const activeFilterBadges: { key: string; label: string }[] = [];
  for (const section of filterSections) {
    const val = activeValues[section.key];
    if (val) {
      const item = section.items.find((i) => i.value === val);
      if (item) {
        activeFilterBadges.push({
          key: section.key,
          label: locale === 'fr' ? item.label_fr : item.label_en,
        });
      }
    }
  }

  return (
    <div className="mb-6 space-y-3 bg-stone-50 rounded-xl p-4 border border-stone-200">
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400 pointer-events-none" />
        <Input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={t('searchPlaceholder')}
          aria-label={t('searchPlaceholder')}
          className="h-11 pl-9 pr-9 rounded-lg"
        />
        {searchInput && (
          <button
            type="button"
            onClick={() => setSearchInput('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
            aria-label={t('clearFilters')}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Mobile: toggle button + result count row */}
      <div className="flex items-center justify-between md:hidden">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setFiltersExpanded(!filtersExpanded)}
          className="gap-1.5 min-h-[44px]"
        >
          {t('filters')}
          {activeFilterCount > 0 && (
            <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-teal-600 text-white text-[10px] font-bold">
              {activeFilterCount}
            </span>
          )}
          {filtersExpanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </Button>
        <ResultCount loading={loading} count={courseCount} t={t} />
      </div>

      {/* Mobile: active filter badges when collapsed */}
      {!filtersExpanded && activeFilterBadges.length > 0 && (
        <div className="flex flex-wrap gap-1.5 md:hidden">
          {activeFilterBadges.map(({ key, label }) => (
            <Badge
              key={key}
              variant="secondary"
              className="gap-1 cursor-pointer hover:bg-stone-200"
              onClick={() => onUpdateFilter(key, null)}
            >
              {label}
              <X className="h-3 w-3" />
            </Badge>
          ))}
        </div>
      )}

      {/* Filter sections — always visible on desktop, toggle on mobile */}
      <div className={`space-y-3 ${filtersExpanded ? 'block' : 'hidden'} md:block`}>
        {filterSections.map((section) => (
          <FilterChips
            key={section.key}
            section={section}
            active={activeValues[section.key]}
            locale={locale}
            onToggle={onUpdateFilter}
          />
        ))}
      </div>

      {/* Desktop: result count + clear row */}
      <div className="hidden md:flex items-center justify-between pt-1">
        <ResultCount loading={loading} count={courseCount} t={t} />
        {totalActiveCount > 0 && (
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 font-medium"
          >
            <X className="h-3 w-3" />
            {t('clearFilters')}
          </button>
        )}
      </div>

      {/* Mobile: clear filters inside expanded panel */}
      {filtersExpanded && totalActiveCount > 0 && (
        <div className="flex justify-end md:hidden">
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 font-medium"
          >
            <X className="h-3 w-3" />
            {t('clearFilters')}
          </button>
        </div>
      )}
    </div>
  );
}

function ResultCount({
  loading,
  count,
  t,
}: {
  loading: boolean;
  count: number;
  t: ReturnType<typeof useTranslations<'Courses'>>;
}) {
  if (loading) {
    return <Loader2 className="h-4 w-4 animate-spin text-stone-400" />;
  }
  return (
    <span className="text-sm text-stone-500">
      {t('showingCourses', { count })}
    </span>
  );
}
