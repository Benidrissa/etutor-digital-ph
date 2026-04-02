'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CourseCard, type CourseData } from '@/components/courses/course-card';
import { apiFetch } from '@/lib/api';
import { Search } from 'lucide-react';

interface Enrollment {
  course: CourseData;
  status: string;
  completion_pct: number;
}

export function CourseCatalogClient() {
  const t = useTranslations('Courses');
  const [courses, setCourses] = useState<CourseData[]>([]);
  const [enrolledIds, setEnrolledIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [domain, setDomain] = useState('');
  const [domains, setDomains] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [enrolling, setEnrolling] = useState<string | null>(null);

  const fetchCourses = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (domain) params.set('domain', domain);
      if (search) params.set('search', search);

      const data = await apiFetch<{ courses: CourseData[]; total: number }>(
        `/api/v1/courses?${params.toString()}`
      );
      setCourses(data.courses);

      const uniqueDomains = Array.from(
        new Set(data.courses.map((c) => c.domain).filter(Boolean) as string[])
      );
      setDomains(uniqueDomains);
    } catch {
      setError(t('error'));
    } finally {
      setLoading(false);
    }
  }, [domain, search, t]);

  const fetchEnrollments = useCallback(async () => {
    try {
      const data = await apiFetch<Enrollment[]>('/api/v1/courses/enrolled');
      setEnrolledIds(new Set(data.map((e) => e.course.id)));
    } catch {
      // not authenticated — ignore
    }
  }, []);

  useEffect(() => {
    fetchCourses();
    fetchEnrollments();
  }, [fetchCourses, fetchEnrollments]);

  const handleEnroll = async (courseId: string) => {
    setEnrolling(courseId);
    try {
      await apiFetch(`/api/v1/courses/${courseId}/enroll`, { method: 'POST' });
      setEnrolledIds((prev) => new Set([...prev, courseId]));
    } catch {
      // surface error to user in a real implementation
    } finally {
      setEnrolling(null);
    }
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-64 rounded-lg bg-stone-100 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return <p className="text-center text-stone-500 py-12">{error}</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('searchPlaceholder')}
            className="pl-9"
          />
        </div>
        {domains.length > 0 && (
          <Select value={domain} onValueChange={setDomain}>
            <SelectTrigger className="w-full sm:w-52">
              <SelectValue placeholder={t('allDomains')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">{t('allDomains')}</SelectItem>
              {domains.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {courses.length === 0 ? (
        <div className="text-center py-16 text-stone-500">
          <p className="text-lg font-medium">{t('noCourses')}</p>
          <p className="text-sm mt-1">{t('noCoursesDescription')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {courses.map((course) => (
            <CourseCard
              key={course.id}
              course={course}
              isEnrolled={enrolledIds.has(course.id)}
              onEnroll={handleEnroll}
              enrolling={enrolling === course.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
