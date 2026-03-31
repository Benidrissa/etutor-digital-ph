'use client';

import { useTranslations, useLocale } from 'next-intl';
import { ModuleCard } from './module-card';
import { 
  CURRICULUM_MODULES, 
  LEVEL_INFO, 
  getModulesByLevel, 
  isModuleUnlocked, 
  getLevelProgress 
} from '@/lib/modules';

interface ModuleMapProps {
  onModuleClick: (moduleId: string) => void;
}

export function ModuleMap({ onModuleClick }: ModuleMapProps) {
  const t = useTranslations('ModuleMap');
  const locale = useLocale() as 'en' | 'fr';
  
  const levels = [1, 2, 3, 4] as const;
  
  return (
    <div className="space-y-8">
      {levels.map((level) => {
        const levelModules = getModulesByLevel(level);
        const levelProgress = getLevelProgress(level);
        const levelInfo = LEVEL_INFO[level];
        
        return (
          <div key={level} className="space-y-4">
            {/* Level Header */}
            <div className="border-b border-stone-200 pb-4">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div>
                  <h3 className="text-lg font-medium text-stone-900">
                    {levelInfo.title[locale]}
                  </h3>
                  <p className="text-sm text-stone-600">
                    {levelInfo.description[locale]}
                  </p>
                </div>
                <div className="flex flex-col sm:items-end gap-1">
                  <div className="text-sm text-stone-600">
                    {t('progress', { 
                      completed: levelProgress.completedModules,
                      total: levelProgress.totalModules 
                    })}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 rounded-full bg-stone-200">
                      <div 
                        className="h-2 rounded-full bg-teal-500 transition-all duration-500"
                        style={{ width: `${levelProgress.averageCompletion}%` }}
                      />
                    </div>
                    <span className="text-xs text-stone-500">
                      {levelProgress.averageCompletion}%
                    </span>
                  </div>
                </div>
              </div>
            </div>
            
            {/* Module Grid */}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {levelModules.map((module) => {
                const unlocked = isModuleUnlocked(module, CURRICULUM_MODULES);
                
                return (
                  <ModuleCard
                    key={module.id}
                    module={module}
                    isUnlocked={unlocked}
                    onClick={() => onModuleClick(module.id)}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
      
      {/* Overall Progress Summary */}
      <div className="mt-8 rounded-lg bg-teal-50 p-6 text-center">
        <h3 className="text-lg font-semibold text-teal-900">
          {t('overallProgress')}
        </h3>
        <div className="mt-4 space-y-2">
          {levels.map((level) => {
            const progress = getLevelProgress(level);
            return (
              <div key={level} className="flex items-center justify-between">
                <span className="text-sm text-teal-700">
                  {LEVEL_INFO[level].title[locale]}
                </span>
                <span className="text-sm font-medium text-teal-800">
                  {progress.completedModules}/{progress.totalModules} {t('modulesCompleted')}
                </span>
              </div>
            );
          })}
        </div>
        <div className="mt-4 text-xs text-teal-600">
          {t('totalHours', { count: 320 })} • {t('estimatedCompletion')}
        </div>
      </div>
    </div>
  );
}