'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { BookOpen } from 'lucide-react';

interface SourceCitationsProps {
  sources: string[];
  className?: string;
}

export function SourceCitations({ sources, className }: SourceCitationsProps) {
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const t = useTranslations('SourceCitations');

  const handleSourceClick = (source: string, index: number) => {
    setSelectedSource(selectedSource === source ? null : source);
    
    // Focus management for accessibility
    const element = document.getElementById(`source-${index}`);
    element?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  return (
    <div className={`border-t pt-6 mt-8 ${className || ''}`}>
      <div className="flex items-center gap-2 mb-4">
        <BookOpen className="w-5 h-5 text-gray-600" />
        <h3 className="font-semibold text-gray-900">{t('title')}</h3>
      </div>
      
      <div className="space-y-2">
        {sources.map((source, index) => (
          <div key={index} id={`source-${index}`} className="group">
            <button
              type="button"
              onClick={() => handleSourceClick(source, index)}
              className="flex items-start gap-2 w-full text-left p-2 rounded-md
                       hover:bg-gray-50 focus:bg-gray-50 focus:outline-none
                       focus:ring-2 focus:ring-teal-500 focus:ring-offset-1
                       transition-colors"
              aria-expanded={selectedSource === source}
              aria-describedby={selectedSource === source ? `source-details-${index}` : undefined}
            >
              <span className="inline-flex items-center justify-center w-6 h-6 
                             bg-teal-100 text-teal-700 text-xs font-medium rounded-full
                             flex-shrink-0 mt-0.5">
                {index + 1}
              </span>
              <span className="text-sm text-gray-700 group-hover:text-gray-900 transition-colors">
                {source}
              </span>
            </button>
            
            {selectedSource === source && (
              <div 
                id={`source-details-${index}`}
                className="ml-8 mt-2 p-3 bg-teal-50 rounded-md border border-teal-100"
                role="region"
                aria-label={t('sourceDetails')}
              >
                <p className="text-sm text-gray-600">
                  {t('clickToView')} {source}
                </p>
                {/* This would link to actual reference material in a real implementation */}
                <div className="mt-2 text-xs text-gray-500">
                  {t('availableInLibrary')}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      
      <div className="mt-4 text-xs text-gray-500">
        {t('footnote', { count: sources.length })}
      </div>
    </div>
  );
}