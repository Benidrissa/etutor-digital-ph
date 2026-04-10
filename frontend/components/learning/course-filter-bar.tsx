'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Search, X, Loader2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { type FilterSection } from './filter-chips';
import { useDebounce } from '@/lib/hooks/use-debounce';

const ALL_VALUE = '__all__';

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
  const [searchInput, setSearchInput] = useState(activeSearch ?? '');
  const debouncedSearch = useDebounce(searchInput, 300);

  // Reset local input when activeSearch is cleared externally (e.g. clearFilters)
  const [prevSearchKey, setPrevSearchKey] = useState(activeSearch ?? '');
  if ((activeSearch ?? '') !== prevSearchKey) {
    setPrevSearchKey(activeSearch ?? '');
    if ((activeSearch ?? '') === '' && searchInput !== '') {
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

  return (
    <div className="mb-6 space-y-3 bg-stone-50 rounded-xl p-4 border border-stone-200">
      {/* Row 1: Search + Dropdowns */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Search input */}
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400 pointer-events-none" />
          <Input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchPlaceholder')}
            className="h-10 pl-9 pr-9 rounded-lg"
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

        {/* Filter dropdowns */}
        <div className="flex gap-2 flex-wrap sm:flex-nowrap">
          {filterSections.map((section) => (
            <Select
              key={section.key}
              value={activeValues[section.key] ?? ALL_VALUE}
              onValueChange={(val) =>
                onUpdateFilter(section.key, val === ALL_VALUE ? null : val)
              }
            >
              <SelectTrigger className="h-10 min-w-[130px] text-xs">
                <SelectValue placeholder={section.label} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>
                  {section.label} — {t('all')}
                </SelectItem>
                {section.items.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {locale === 'fr' ? item.label_fr : item.label_en}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ))}
        </div>
      </div>

      {/* Row 2: Result count + Clear */}
      <div className="flex items-center justify-between">
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-stone-400" />
        ) : (
          <span className="text-sm text-stone-500">
            {t('showingCourses', { count: courseCount })}
          </span>
        )}
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
    </div>
  );
}
