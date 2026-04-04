'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { GraduationCap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseCard } from '@/components/learning/course-card';
import { getCourses, type CourseResponse } from '@/lib/api';

export default function CoursesPage() {
  const t = useTranslations('Courses');
  const [courses, setCourses] = useState<CourseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCourses()
      .then((data) => {
        if (!cancelled) {
          setCourses(data);
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

  const handleRetry = () => {
    setError(false);
    setLoading(true);
    getCourses()
      .then((data) => {
        setCourses(data);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  };

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-bold text-stone-900 mb-2">
          {t('title')}
        </h1>
        <p className="text-stone-600 text-lg">
          {t('subtitle')}
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-stone-500 text-sm">{t('loading')}</p>
        </div>
      )}

      {error && (
        <div className="flex flex-col items-center justify-center py-12 gap-4">
          <p className="text-red-500 text-sm">{t('error')}</p>
          <Button variant="outline" size="sm" onClick={handleRetry}>
            {t('tryAgain')}
          </Button>
        </div>
      )}

      {!loading && !error && courses.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <div className="rounded-full bg-teal-50 p-6">
            <GraduationCap className="h-12 w-12 text-teal-600" aria-hidden="true" />
          </div>
          <h2 className="text-lg font-semibold text-stone-900">{t('noCourses')}</h2>
          <p className="text-stone-500 text-sm max-w-sm">{t('noCoursesDescription')}</p>
        </div>
      )}

      {!loading && !error && courses.length > 0 && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      )}
    </div>
  );
}
