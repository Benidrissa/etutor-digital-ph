'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { ModuleCard } from './module-card';
import type { Module } from '@/lib/modules';
import { getAllModuleProgress, getMyEnrollments, type ModuleProgressResponse, type CourseWithEnrollment } from '@/lib/api';

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
      : apiStatus === 'not_started'
      ? 'not-started'
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

interface CourseGroup {
  courseId: string;
  courseName: string;
  modules: Module[];
}

export function ModuleMap({ onModuleClick, courseId }: ModuleMapProps) {
  const t = useTranslations('ModuleMap');
  const locale = useLocale() as 'en' | 'fr';

  const [courseGroups, setCourseGroups] = useState<CourseGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        if (courseId) {
          const [progressData, enrollments] = await Promise.all([
            getAllModuleProgress(courseId),
            getMyEnrollments(),
          ]);
          if (cancelled) return;
          const course = enrollments.find((c: CourseWithEnrollment) => c.id === courseId);
          const courseName = course
            ? (locale === 'fr' ? course.title_fr : course.title_en)
            : t('title');
          setCourseGroups([{
            courseId,
            courseName,
            modules: progressData.map(apiProgressToModule),
          }]);
        } else {
          const enrollments = await getMyEnrollments();
          if (cancelled) return;
          const progressResults = await Promise.all(
            enrollments.map((course: CourseWithEnrollment) =>
              getAllModuleProgress(course.id).then((data) => ({ course, data }))
            )
          );
          if (cancelled) return;
          const groups: CourseGroup[] = progressResults
            .filter(({ data }) => data.length > 0)
            .map(({ course, data }) => ({
              courseId: course.id,
              courseName: locale === 'fr' ? course.title_fr : course.title_en,
              modules: data.map(apiProgressToModule),
            }));
          setCourseGroups(groups);
        }
        setLoading(false);
      } catch {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      }
    }

    loadData();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, locale]);

  const getGroupProgress = (modules: Module[]) => {
    const completedModules = modules.filter((m) => m.status === 'completed').length;
    const totalModules = modules.length;
    const averageCompletion =
      totalModules > 0
        ? modules.reduce((sum, m) => sum + m.completionPercentage, 0) / totalModules
        : 0;
    return { completedModules, totalModules, averageCompletion: Math.round(averageCompletion) };
  };

  const isModuleUnlocked = (module: Module): boolean => module.status !== 'locked';

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
      {courseGroups.map((group) => {
        const groupProgress = getGroupProgress(group.modules);

        return (
          <div key={group.courseId} className="space-y-4">
            <div className="border-b border-stone-200 pb-4">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div>
                  <h3 className="text-lg font-medium text-stone-900">
                    {group.courseName}
                  </h3>
                </div>
                <div className="flex flex-col sm:items-end gap-1">
                  <div className="text-sm text-stone-600">
                    {t('progress', {
                      completed: groupProgress.completedModules,
                      total: groupProgress.totalModules,
                    })}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 rounded-full bg-stone-200">
                      <div
                        className="h-2 rounded-full bg-teal-500 transition-all duration-500"
                        style={{ width: `${groupProgress.averageCompletion}%` }}
                      />
                    </div>
                    <span className="text-xs text-stone-500">
                      {groupProgress.averageCompletion}%
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {group.modules.map((module) => {
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

      {courseGroups.length > 0 && (
        <div className="mt-8 rounded-lg bg-teal-50 p-6 text-center">
          <h3 className="text-lg font-semibold text-teal-900">
            {t('overallProgress')}
          </h3>
          <div className="mt-4 space-y-2">
            {courseGroups.map((group) => {
              const progress = getGroupProgress(group.modules);
              return (
                <div key={group.courseId} className="flex items-center justify-between">
                  <span className="text-sm text-teal-700">
                    {group.courseName}
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
