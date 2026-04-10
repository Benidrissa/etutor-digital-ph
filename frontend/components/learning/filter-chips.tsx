'use client';

export interface FilterSection {
  key: string;
  label: string;
  items: { value: string; label_fr: string; label_en: string }[];
}

export function FilterChips({
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
      <div className="flex flex-wrap gap-1.5">
        {section.items.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() =>
              onToggle(section.key, active === item.value ? null : item.value)
            }
            className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors min-h-[44px] ${
              active === item.value
                ? 'bg-teal-700 text-white ring-2 ring-teal-300/50 ring-offset-1'
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
