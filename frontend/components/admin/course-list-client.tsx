'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { BookOpen, Clock, Loader2, Plus } from 'lucide-react';
import { authClient, AuthError } from '@/lib/auth';
import { useRouter } from 'next/navigation';
import { CourseWizardClient } from './course-wizard-client';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CourseData {
  id: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  domain: string | null;
  status: string;
  module_count: number;
  estimated_hours: number;
  created_at: string;
  published_at: string | null;
}

export function CourseListClient() {
  const t = useTranslations('AdminCourses');
  const locale = useLocale() as 'fr' | 'en';
  const router = useRouter();

  const [courses, setCourses] = useState<CourseData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showWizard, setShowWizard] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const getToken = useCallback(async () => {
    try {
      return await authClient.getValidToken();
    } catch (err) {
      if (err instanceof AuthError && err.status === 401) {
        router.push('/login');
      }
      throw err;
    }
  }, [router]);

  const fetchCourses = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: CourseData[] = await res.json();
      setCourses(data);
    } catch {
      setError(t('error'));
    } finally {
      setLoading(false);
    }
  }, [getToken, t]);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  const handlePublish = async (courseId: string) => {
    setActionLoading(courseId);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}/publish`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchCourses();
    } catch {
    } finally {
      setActionLoading(null);
    }
  };

  const handleArchive = async (courseId: string) => {
    setActionLoading(courseId);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}/archive`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchCourses();
    } catch {
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (courseId: string) => {
    setActionLoading(courseId);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchCourses();
    } catch {
    } finally {
      setActionLoading(null);
    }
  };

  const statusBadge = (status: string) => {
    if (status === 'published') {
      return (
        <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
          {t('statusPublished')}
        </Badge>
      );
    }
    if (status === 'archived') {
      return (
        <Badge className="bg-orange-100 text-orange-800 hover:bg-orange-100">
          {t('statusArchived')}
        </Badge>
      );
    }
    return (
      <Badge variant="secondary">{t('statusDraft')}</Badge>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>{t('loading')}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-8 text-sm text-destructive">
        {error}
        <Button variant="link" className="ml-2 p-0 text-sm" onClick={fetchCourses}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <>
      {showWizard && (
        <CourseWizardClient
          onClose={() => setShowWizard(false)}
          onCreated={() => {
            setShowWizard(false);
            fetchCourses();
          }}
        />
      )}

      <div className="flex items-center justify-between mb-6">
        <p className="text-sm text-muted-foreground">
          {courses.length === 0 ? t('noCourses') : `${courses.length} cours`}
        </p>
        <Button onClick={() => setShowWizard(true)} className="min-h-11 gap-2">
          <Plus className="h-4 w-4" />
          {t('createCourse')}
        </Button>
      </div>

      {courses.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BookOpen className="mb-4 h-12 w-12 text-muted-foreground/40" />
          <p className="font-medium">{t('noCourses')}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t('noCoursesDesc')}</p>
          <Button className="mt-4 min-h-11" onClick={() => setShowWizard(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t('createCourse')}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {courses.map((course) => (
            <div
              key={course.id}
              className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  {statusBadge(course.status)}
                  {course.domain && (
                    <Badge variant="outline" className="text-xs">
                      {course.domain}
                    </Badge>
                  )}
                </div>
                <p className="font-medium leading-tight">
                  {locale === 'fr' ? course.title_fr : course.title_en}
                </p>
                <p className="text-sm text-muted-foreground">
                  {locale === 'fr' ? course.title_en : course.title_fr}
                </p>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <BookOpen className="h-3 w-3" />
                    {t('modules', { count: course.module_count })}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {t('hours', { count: course.estimated_hours })}
                  </span>
                </div>
              </div>

              <div className="flex shrink-0 flex-wrap gap-2">
                {course.status === 'draft' && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="sm"
                        className="min-h-9 bg-green-600 hover:bg-green-700"
                        disabled={actionLoading === course.id}
                      >
                        {actionLoading === course.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          t('publish')
                        )}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t('confirmPublish')}</AlertDialogTitle>
                        <AlertDialogDescription>{t('confirmPublishDesc')}</AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
                        <AlertDialogAction onClick={() => handlePublish(course.id)}>
                          {t('confirm')}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}

                {course.status === 'published' && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="sm"
                        variant="outline"
                        className="min-h-9"
                        disabled={actionLoading === course.id}
                      >
                        {actionLoading === course.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          t('archive')
                        )}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t('confirmArchive')}</AlertDialogTitle>
                        <AlertDialogDescription>{t('confirmArchiveDesc')}</AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
                        <AlertDialogAction onClick={() => handleArchive(course.id)}>
                          {t('confirm')}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}

                {course.status !== 'published' && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="min-h-9 text-destructive hover:text-destructive"
                        disabled={actionLoading === course.id}
                      >
                        {t('delete')}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>{t('confirmDelete')}</AlertDialogTitle>
                        <AlertDialogDescription>{t('confirmDeleteDesc')}</AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
                        <AlertDialogAction
                          className="bg-destructive hover:bg-destructive/90"
                          onClick={() => handleDelete(course.id)}
                        >
                          {t('confirm')}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
