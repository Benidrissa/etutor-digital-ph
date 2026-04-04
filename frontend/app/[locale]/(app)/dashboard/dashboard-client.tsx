'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import { ModuleMap } from '@/components/learning/module-map';
import { getMyEnrollments, type CourseWithEnrollment } from '@/lib/api';

export function DashboardClient() {
  const t = useTranslations('Dashboard');
  const locale = useLocale() as 'en' | 'fr';
  const router = useRouter();

  const [enrollments, setEnrollments] = useState<CourseWithEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedCourseId, setExpandedCourseId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMyEnrollments()
      .then((data) => {
        if (!cancelled) {
          setEnrollments(data);
          if (data.length === 1) {
            setExpandedCourseId(data[0].id);
          }
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleModuleClick = (moduleId: string) => {
    router.push(`/modules/${moduleId}`);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-stone-500 text-sm">{t('loading')}</p>
      </div>
    );
  }

  if (enrollments.length === 0) {
    return (
      <div className="rounded-lg bg-stone-50 border border-stone-200 p-8 text-center">
        <p className="text-stone-600 text-sm">{t('noEnrollments')}</p>
        <button
          className="mt-4 text-teal-600 text-sm font-medium underline-offset-2 hover:underline min-h-11"
          onClick={() => router.push('/courses')}
        >
          {t('browseCourses')}
        </button>
      </div>
    );
  }

  if (enrollments.length === 1) {
    return (
      <div className="space-y-4">
        <ModuleMap
          courseId={enrollments[0].id}
          onModuleClick={handleModuleClick}
        />
        <button
          className="w-full text-center text-teal-600 text-sm font-medium underline-offset-2 hover:underline min-h-11 rounded-lg border border-dashed border-teal-200 py-3 hover:bg-teal-50 transition-colors"
          onClick={() => router.push('/courses')}
        >
          {t('browseMoreCourses')}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {enrollments.map((course) => {
        const isExpanded = expandedCourseId === course.id;
        const title = locale === 'fr' ? course.title_fr : course.title_en;

        return (
          <div key={course.id} className="rounded-lg border border-stone-200 overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-4 py-4 bg-white text-left hover:bg-stone-50 transition-colors min-h-11"
              onClick={() =>
                setExpandedCourseId(isExpanded ? null : course.id)
              }
              aria-expanded={isExpanded}
            >
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold text-stone-900 truncate">
                  {title}
                </h3>
                {course.course_domain?.[0] && (
                  <span className="text-xs text-stone-500">
                    {locale === 'fr' ? course.course_domain[0].label_fr : course.course_domain[0].label_en}
                  </span>
                )}
              </div>
              <span
                className="ml-3 text-stone-400 shrink-0 transition-transform duration-200"
                style={{ transform: isExpanded ? 'rotate(180deg)' : 'none' }}
                aria-hidden="true"
              >
                ▾
              </span>
            </button>

            {isExpanded && (
              <div className="px-4 pb-6 pt-2 bg-white border-t border-stone-100">
                <ModuleMap
                  courseId={course.id}
                  onModuleClick={handleModuleClick}
                />
              </div>
            )}
          </div>
        );
      })}
      <button
        className="w-full text-center text-teal-600 text-sm font-medium underline-offset-2 hover:underline min-h-11 rounded-lg border border-dashed border-teal-200 py-3 hover:bg-teal-50 transition-colors"
        onClick={() => router.push('/courses')}
      >
        {t('browseMoreCourses')}
      </button>
    </div>
  );
}
