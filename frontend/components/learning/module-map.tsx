'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { ModuleCard } from './module-card';
import type { Module } from '@/lib/modules';
import { getAllModuleProgress, type ModuleProgressResponse } from '@/lib/api';

interface ModuleMapProps {
  onModuleClick: (moduleId: string) => void;
  courseId?: string;
}

function apiProgressToModule(p: ModuleProgressResponse): Module {
  const apiStatus = p.status;
  const mappedStatus: Module['status'] =
    apiStatus === 'completed'
      ? 'completed'
      : apiStatus === 'in_progress'
      ? 'in-progress'
      : 'locked';

  return {
    id: p.module_id,
    number: p.module_number ?? 0,
    title: { en: p.title_en, fr: p.title_fr },
    description:
      p.description_en || p.description_fr
        ? { en: p.description_en ?? '', fr: p.description_fr ?? '' }
        : undefined,
    level: (p.level as 1 | 2 | 3 | 4),
    status: mappedStatus,
    completionPercentage: p.completion_pct,
    estimatedHours: p.estimated_hours,
    prerequisites: [],
  };
}

const LEVEL_LABELS: Record<number, { en: string; fr: string }> = {
  1: { en: 'Level 1: Beginner', fr: 'Niveau 1 : Débutant' },
  2: { en: 'Level 2: Intermediate', fr: 'Niveau 2 : Intermédiaire' },
  3: { en: 'Level 3: Advanced', fr: 'Niveau 3 : Avancé' },
  4: { en: 'Level 4: Expert', fr: 'Niveau 4 : Expert' },
};

export function ModuleMap({ onModuleClick, courseId }: ModuleMapProps) {
  const t = useTranslations('ModuleMap');
  const locale = useLocale() as 'en' | 'fr';

  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAllModuleProgress(courseId)
      .then((data) => {
        if (!cancelled) {
          setModules(data.map(apiProgressToModule));
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
  }, [courseId]);

  const levels = Array.from(new Set(modules.map((m) => m.level))).sort() as (1 | 2 | 3 | 4)[];

  const getLevelModules = (level: number) => modules.filter((m) => m.level === level);

  const getLevelProgress = (level: number) => {
    const levelModules = getLevelModules(level);
    const completedModules = levelModules.filter((m) => m.status === 'completed').length;
    const totalModules = levelModules.length;
    const averageCompletion =
      totalModules > 0
        ? levelModules.reduce((sum, m) => sum + m.completionPercentage, 0) / totalModules
        : 0;
    return { completedModules, totalModules, averageCompletion: Math.round(averageCompletion) };
  };

  const isModuleUnlocked = (module: Module): boolean => module.status !== 'locked';

  const getLevelLabel = (level: number): string => {
    const label = LEVEL_LABELS[level];
    if (label) return label[locale];
    return locale === 'fr' ? `Niveau ${level}` : `Level ${level}`;
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
        const levelModules = getLevelModules(level);
        const levelProgress = getLevelProgress(level);

        return (
          <div key={level} className="space-y-4">
            <div className="border-b border-stone-200 pb-4">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div>
                  <h3 className="text-lg font-medium text-stone-900">
                    {getLevelLabel(level)}
                  </h3>
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

      {levels.length > 0 && (
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
                    {getLevelLabel(level)}
                  </span>
                  <span className="text-sm font-medium text-teal-800">
                    {progress.completedModules}/{progress.totalModules} {t('modulesCompleted')}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-4 text-xs text-teal-600">
            {t('estimatedCompletion')}
          </div>
        </div>
      )}
    </div>
  );
}
