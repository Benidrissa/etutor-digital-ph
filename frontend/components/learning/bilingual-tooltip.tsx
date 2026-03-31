'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';

interface BilingualTooltipProps {
  children: React.ReactNode;
  term: string;
  termFr: string;
  termEn: string;
  className?: string;
}

export function BilingualTooltip({ children, term, termFr, termEn, className }: BilingualTooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const t = useTranslations('BilingualTooltip');

  const handleClick = () => {
    setIsOpen(!isOpen);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setIsOpen(!isOpen);
    }
  };

  return (
    <span className="relative inline">
      <button
        type="button"
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        className={`
          underline decoration-teal-300 decoration-2 cursor-pointer
          hover:decoration-teal-500 transition-colors
          focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-1
          rounded-sm
          ${className || ''}
        `}
        aria-expanded={isOpen}
        aria-describedby={isOpen ? `tooltip-${term}` : undefined}
      >
        {children}
      </button>
      
      {isOpen && (
        <div
          id={`tooltip-${term}`}
          className="absolute z-10 bottom-full left-1/2 transform -translate-x-1/2 mb-2
                     bg-gray-900 text-white text-sm rounded-lg px-3 py-2
                     min-w-48 max-w-72 shadow-lg"
          role="tooltip"
        >
          <div className="font-medium mb-1">{term}</div>
          <div className="text-xs space-y-1 text-gray-300">
            <div><strong>{t('french')}:</strong> {termFr}</div>
            <div><strong>{t('english')}:</strong> {termEn}</div>
          </div>
          {/* Arrow */}
          <div className="absolute top-full left-1/2 transform -translate-x-1/2 
                         border-l-4 border-r-4 border-t-4 
                         border-transparent border-t-gray-900" />
        </div>
      )}
    </span>
  );
}