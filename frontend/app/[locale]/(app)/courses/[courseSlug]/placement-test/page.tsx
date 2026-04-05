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

export default async function CoursePreassessmentPage({ params }: CoursePreassessmentPageProps) {
  const { locale, courseSlug } = await params;

  let course: CourseDetail | null = null;
  try {
    course = await apiFetch<CourseDetail>(`/api/v1/courses/${courseSlug}`);
  } catch {
    // Proceed without course name if fetch fails
  }

  const courseName = locale === 'fr' ? (course?.title_fr ?? courseSlug) : (course?.title_en ?? courseSlug);

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <PlacementTestContainer
        locale={locale}
        courseId={course?.id ?? courseSlug}
        courseName={courseName}
      />
    </div>
  );
}
