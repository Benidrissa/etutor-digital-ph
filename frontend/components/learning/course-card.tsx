'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CheckCircle, Clock, BookOpen, GraduationCap } from 'lucide-react';
import { enrollInCourse, type CourseResponse } from '@/lib/api';

const LEVEL_COLORS: Record<string, string> = {
  beginner: 'bg-green-50 text-green-700 border-green-200',
  intermediate: 'bg-blue-50 text-blue-700 border-blue-200',
  advanced: 'bg-amber-50 text-amber-700 border-amber-200',
  expert: 'bg-red-50 text-red-700 border-red-200',
};

interface CourseCardProps {
  course: CourseResponse;
}

export function CourseCard({ course }: CourseCardProps) {
  const t = useTranslations('Courses');
  const locale = useLocale() as 'en' | 'fr';
  const router = useRouter();
  const [isEnrolled, setIsEnrolled] = useState(course.enrolled);
  const [enrolling, setEnrolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const title = locale === 'fr' ? course.title_fr : course.title_en;
  const description = locale === 'fr' ? course.description_fr : course.description_en;

  const handleEnroll = async () => {
    setEnrolling(true);
    setError(null);
    try {
      await enrollInCourse(course.id);
      setIsEnrolled(true);
    } catch {
      setError(t('enrollError'));
    } finally {
      setEnrolling(false);
    }
  };

  const handleViewModules = () => {
    router.push(`/modules?course_id=${course.id}`);
  };

  return (
    <Card className="flex flex-col h-full border border-stone-200 hover:shadow-md transition-shadow duration-200">
      {course.cover_image_url && (
        <div className="relative h-40 overflow-hidden rounded-t-lg bg-teal-50">
          <img
            src={course.cover_image_url}
            alt={title}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      {!course.cover_image_url && (
        <div className="h-40 rounded-t-lg bg-gradient-to-br from-teal-600 to-amber-500 flex items-center justify-center">
          <GraduationCap className="h-16 w-16 text-white opacity-80" />
        </div>
      )}

      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base leading-tight text-stone-900 line-clamp-2">
            {title}
          </CardTitle>
          {isEnrolled && (
            <CheckCircle className="h-5 w-5 text-teal-600 shrink-0 mt-0.5" aria-hidden="true" />
          )}
        </div>

        {/* Taxonomy badges — labels come from API, no i18n lookup */}
        <div className="flex flex-wrap gap-1 mt-1">
          {course.course_domain?.map((d) => (
            <span
              key={d.value}
              className="inline-block text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5"
            >
              {locale === 'fr' ? d.label_fr : d.label_en}
            </span>
          ))}
          {course.course_level?.map((l) => (
            <span
              key={l.value}
              className={`inline-block text-[10px] font-medium border rounded-full px-2 py-0.5 ${
                LEVEL_COLORS[l.value] || 'bg-stone-50 text-stone-700 border-stone-200'
              }`}
            >
              {locale === 'fr' ? l.label_fr : l.label_en}
            </span>
          ))}
          {course.audience_type?.map((a) => (
            <span
              key={a.value}
              className="inline-block text-[10px] font-medium text-violet-700 bg-violet-50 border border-violet-200 rounded-full px-2 py-0.5"
            >
              {locale === 'fr' ? a.label_fr : a.label_en}
            </span>
          ))}
        </div>
      </CardHeader>

      <CardContent className="flex flex-col flex-1 pt-0 gap-3">
        {description && (
          <p className="text-sm text-stone-600 line-clamp-2">{description}</p>
        )}

        <div className="flex items-center gap-4 text-xs text-stone-500">
          <div className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{t('hours', { count: course.estimated_hours })}</span>
          </div>
          <div className="flex items-center gap-1">
            <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{t('modules', { count: course.module_count })}</span>
          </div>
        </div>

        {error && (
          <p className="text-xs text-red-600" role="alert">{error}</p>
        )}

        <div className="mt-auto pt-2">
          {isEnrolled ? (
            <Button
              variant="default"
              size="sm"
              className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
              onClick={handleViewModules}
            >
              {t('viewModules')}
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
              onClick={handleEnroll}
              disabled={enrolling}
            >
              {enrolling ? t('enrolling') : t('enroll')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
