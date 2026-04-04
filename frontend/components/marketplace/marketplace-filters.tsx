'use client';

import { useTranslations } from 'next-intl';
import { X } from 'lucide-react';
import { type TaxonomyItem, type MarketplacePriceFilter } from '@/lib/api';
import { cn } from '@/lib/utils';

interface MarketplaceFiltersProps {
  taxonomy: {
    domains: TaxonomyItem[];
    levels: TaxonomyItem[];
    audience_types: TaxonomyItem[];
  } | null;
  activeDomain: string | null;
  activeLevel: string | null;
  activeAudience: string | null;
  activePrice: MarketplacePriceFilter;
  activeFilterCount: number;
  locale: 'fr' | 'en';
  onToggleFilter: (key: string, value: string | null) => void;
  onClearFilters: () => void;
}

interface FilterChipProps {
  label: string;
  isActive: boolean;
  onClick: () => void;
}

function FilterChip({ label, isActive, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors min-h-[36px]',
        isActive
          ? 'bg-teal-600 text-white'
          : 'bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200'
      )}
    >
      {label}
    </button>
  );
}

export function MarketplaceFilters({
  taxonomy,
  activeDomain,
  activeLevel,
  activeAudience,
  activePrice,
  activeFilterCount,
  locale,
  onToggleFilter,
  onClearFilters,
}: MarketplaceFiltersProps) {
  const t = useTranslations('Marketplace');

  return (
    <div className="space-y-3 bg-stone-50 rounded-xl p-4 border border-stone-200">
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-stone-500 uppercase tracking-wide">
          {t('priceRange')}
        </span>
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {(['all', 'free', 'paid'] as const).map((price) => (
            <FilterChip
              key={price}
              label={t(
                price === 'all'
                  ? 'priceAll'
                  : price === 'free'
                  ? 'priceFree'
                  : 'pricePaid'
              )}
              isActive={activePrice === price}
              onClick={() => onToggleFilter('price', price === 'all' ? null : price)}
            />
          ))}
        </div>
      </div>

      {taxonomy && (
        <>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-stone-500 uppercase tracking-wide">
              {t('domain')}
            </span>
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              <FilterChip
                label={t('allDomains')}
                isActive={!activeDomain}
                onClick={() => onToggleFilter('domain', null)}
              />
              {taxonomy.domains.map((item) => (
                <FilterChip
                  key={item.value}
                  label={locale === 'fr' ? item.label_fr : item.label_en}
                  isActive={activeDomain === item.value}
                  onClick={() =>
                    onToggleFilter(
                      'domain',
                      activeDomain === item.value ? null : item.value
                    )
                  }
                />
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-stone-500 uppercase tracking-wide">
              {t('level')}
            </span>
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              <FilterChip
                label={t('allLevels')}
                isActive={!activeLevel}
                onClick={() => onToggleFilter('level', null)}
              />
              {taxonomy.levels.map((item) => (
                <FilterChip
                  key={item.value}
                  label={locale === 'fr' ? item.label_fr : item.label_en}
                  isActive={activeLevel === item.value}
                  onClick={() =>
                    onToggleFilter(
                      'level',
                      activeLevel === item.value ? null : item.value
                    )
                  }
                />
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-stone-500 uppercase tracking-wide">
              {t('audience')}
            </span>
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              <FilterChip
                label={t('allAudiences')}
                isActive={!activeAudience}
                onClick={() => onToggleFilter('audience', null)}
              />
              {taxonomy.audience_types.map((item) => (
                <FilterChip
                  key={item.value}
                  label={locale === 'fr' ? item.label_fr : item.label_en}
                  isActive={activeAudience === item.value}
                  onClick={() =>
                    onToggleFilter(
                      'audience',
                      activeAudience === item.value ? null : item.value
                    )
                  }
                />
              ))}
            </div>
          </div>
        </>
      )}

      {activeFilterCount > 0 && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-stone-500">
            {t('activeFilters', { count: activeFilterCount })}
          </span>
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 font-medium"
          >
            <X className="h-3 w-3" aria-hidden="true" />
            {t('clearFilters')}
          </button>
        </div>
      )}
    </div>
  );
}
