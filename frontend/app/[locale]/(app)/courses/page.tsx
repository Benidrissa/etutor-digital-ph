'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Input } from '@/components/ui/input';
import { CourseCard, type CourseData } from '@/components/courses/course-card';
import { API_BASE } from '@/lib/api';

async function fetchCourses(search?: string, domain?: string): Promise<CourseData[]> {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (domain) params.set('domain', domain);
  const res = await fetch(`${API_BASE}/api/v1/courses?${params.toString()}`);
  if (!res.ok) return [];
  return res.json();
}

async function enrollInCourse(courseId: string, token: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/v1/courses/${courseId}/enroll`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.ok || res.status === 409;
}

export default function CoursesPage() {
  const t = useTranslations('Courses');
  const [courses, setCourses] = useState<CourseData[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [enrolledIds, setEnrolledIds] = useState<Set<string>>(new Set());
  const [enrollingId, setEnrollingId] = useState<string | null>(null);

  const loadCourses = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await fetchCourses(search || undefined);
      setCourses(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(loadCourses, 300);
    return () => clearTimeout(timer);
  }, [loadCourses]);

  const handleEnroll = async (courseId: string) => {
    if (enrollingId) return;
    setEnrollingId(courseId);
    try {
      const { authClient } = await import('@/lib/auth');
      const token = authClient.getAccessToken() ?? '';
      const ok = await enrollInCourse(courseId, token);
      if (ok) {
        setEnrolledIds((prev) => new Set([...prev, courseId]));
      }
    } finally {
      setEnrollingId(null);
    }
  };

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-900 mb-1">{t('catalog')}</h1>
        <p className="text-stone-600 text-sm">{t('catalogSubtitle')}</p>
      </div>

      <div className="mb-6">
        <Input
          type="search"
          placeholder={t('searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-md"
        />
      </div>

      {loading ? (
        <p className="text-muted-foreground">{t('loading')}</p>
      ) : error ? (
        <p className="text-destructive">{t('error')}</p>
      ) : courses.length === 0 ? (
        <p className="text-muted-foreground">{t('noCoursesFound')}</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <CourseCard
              key={course.id}
              course={course}
              isEnrolled={enrolledIds.has(course.id)}
              onEnroll={handleEnroll}
              enrolling={enrollingId === course.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
