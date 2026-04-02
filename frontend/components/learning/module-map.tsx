'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { ModuleCard } from './module-card';
import {
  CURRICULUM_MODULES,
  LEVEL_INFO,
  getModulesByLevel,
  type Module,
} from '@/lib/modules';
import { getAllModuleProgress, type ModuleProgressResponse } from '@/lib/api';

interface ModuleMapProps {
  onModuleClick: (moduleId: string) => void;
}

function mergeProgressIntoModules(
  apiProgress: ModuleProgressResponse[]
): Module[] {
  const progressByNumber = new Map<number, ModuleProgressResponse>();
  for (const p of apiProgress) {
    if (p.module_number != null) {
      progressByNumber.set(p.module_number, p);
    }
  }

  return CURRICULUM_MODULES.map((mod) => {
    const progress = progressByNumber.get(mod.number);
    if (!progress) return mod;

    const apiStatus = progress.status;
    const mappedStatus: Module['status'] =
      apiStatus === 'completed'
        ? 'completed'
        : apiStatus === 'in_progress'
        ? 'in-progress'
        : 'locked';

    return {
      ...mod,
      status: mappedStatus,
      completionPercentage: progress.completion_pct,
    };
  });
}

export function ModuleMap({ onModuleClick }: ModuleMapProps) {
  const t = useTranslations('ModuleMap');
  const locale = useLocale() as 'en' | 'fr';

  const [modules, setModules] = useState<Module[]>(CURRICULUM_MODULES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAllModuleProgress()
      .then((data) => {
        if (!cancelled) {
          setModules(mergeProgressIntoModules(data));
          setLoading(false);
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
  }, []);

  const levels = [1, 2, 3, 4] as const;

  const getLevelProgress = (level: 1 | 2 | 3 | 4) => {
    const levelModules = modules.filter((m) => m.level === level);
    const completedModules = levelModules.filter((m) => m.status === 'completed').length;
    const totalModules = levelModules.length;
    const averageCompletion =
      totalModules > 0
        ? levelModules.reduce((sum, m) => sum + m.completionPercentage, 0) / totalModules
        : 0;
    return { completedModules, totalModules, averageCompletion: Math.round(averageCompletion) };
  };

  const isModuleUnlocked = (module: Module): boolean => {
    if (module.status !== 'locked') return true;
    if (module.prerequisites.length === 0) return true;
    return false;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-stone-500 text-sm">{t('loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-red-500 text-sm">{t('error')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {levels.map((level) => {
        const levelModules = getModulesByLevel(level).map(
          (m) => modules.find((mod) => mod.id === m.id) ?? m
        );
        const levelProgress = getLevelProgress(level);
        const levelInfo = LEVEL_INFO[level];

        return (
          <div key={level} className="space-y-4">
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
                      total: levelProgress.totalModules,
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

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {levelModules.map((module) => {
                const unlocked = isModuleUnlocked(module);

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
