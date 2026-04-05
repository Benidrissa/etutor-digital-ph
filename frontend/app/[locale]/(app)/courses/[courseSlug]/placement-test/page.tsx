'use client';

import { use, useEffect, useState } from 'react';
import { useLocale } from 'next-intl';
import { PlacementTestContainer } from '@/components/placement/placement-test-container';
import { apiFetch } from '@/lib/api';

interface CoursePreassessmentPageProps {
  params: Promise<{ locale: string; courseSlug: string }>;
}

interface CourseDetail {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
}

export default function CoursePreassessmentPage({ params }: CoursePreassessmentPageProps) {
  const { courseSlug } = use(params);
  const locale = useLocale();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    apiFetch<CourseDetail>(`/api/v1/courses/${courseSlug}`)
      .then(setCourse)
      .catch(() => {
        // Proceed without course details if fetch fails
      })
      .finally(() => setIsLoading(false));
  }, [courseSlug]);

  const courseName = locale === 'fr'
    ? (course?.title_fr ?? courseSlug)
    : (course?.title_en ?? courseSlug);

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/2" />
          <div className="h-4 bg-muted rounded w-3/4" />
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <PlacementTestContainer
        locale={locale}
        courseId={course?.id}
        courseName={courseName}
      />
    </div>
  );
}
