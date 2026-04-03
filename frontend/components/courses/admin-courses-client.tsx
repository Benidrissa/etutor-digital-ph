'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { PlusCircle, Globe } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { API_BASE } from '@/lib/api';
import { authClient } from '@/lib/auth';
import type { CourseData } from './course-card';

type AdminCourse = CourseData & { status: string; created_at: string; published_at: string | null };

async function fetchAdminCourses(token: string): Promise<AdminCourse[]> {
  const res = await fetch(`${API_BASE}/api/v1/admin/courses`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error('Failed to fetch courses');
  return res.json();
}

async function createCourse(data: Record<string, unknown>, token: string): Promise<AdminCourse> {
  const res = await fetch(`${API_BASE}/api/v1/admin/courses`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? 'Failed to create course');
  }
  return res.json();
}

async function publishCourse(courseId: string, token: string): Promise<AdminCourse> {
  const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}/publish`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error('Failed to publish');
  return res.json();
}

export function AdminCoursesClient() {
  const t = useTranslations('AdminCourses');
  const locale = useLocale() as 'fr' | 'en';
  const qc = useQueryClient();
  const token = authClient.getAccessToken() ?? '';

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    slug: '', title_fr: '', title_en: '', domain: '', estimated_hours: 0,
  });
  const [formError, setFormError] = useState('');

  const { data: courses = [], isLoading, isError } = useQuery({
    queryKey: ['admin-courses'],
    queryFn: () => fetchAdminCourses(token),
  });

  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => createCourse(data, token),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-courses'] });
      setShowForm(false);
      setFormData({ slug: '', title_fr: '', title_en: '', domain: '', estimated_hours: 0 });
      setFormError('');
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const publishMutation = useMutation({
    mutationFn: (courseId: string) => publishCourse(courseId, token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-courses'] }),
  });

  const statusBadge = (status: string) => {
    const map: Record<string, 'default' | 'secondary' | 'outline'> = {
      published: 'default',
      draft: 'secondary',
      archived: 'outline',
    };
    return <Badge variant={map[status] ?? 'secondary'}>{t(`status.${status}` as never)}</Badge>;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({ ...formData, estimated_hours: Number(formData.estimated_hours) });
  };

  if (isLoading) return <p className="text-muted-foreground">{t('loading')}</p>;
  if (isError) return <p className="text-destructive">{t('error')}</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {courses.length} {t('allCourses').toLowerCase()}
        </span>
        <Button size="sm" className="min-h-11" onClick={() => setShowForm((v) => !v)}>
          <PlusCircle className="h-4 w-4 mr-2" />
          {t('createCourse')}
        </Button>
      </div>

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('createCourse')}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="slug">{t('form.slug')}</Label>
                <Input
                  id="slug"
                  value={formData.slug}
                  onChange={(e) => setFormData((p) => ({ ...p, slug: e.target.value }))}
                  pattern="[a-z0-9-]+"
                  required
                />
                <p className="text-xs text-muted-foreground">{t('form.slugHelp')}</p>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="title_fr">{t('form.titleFr')}</Label>
                  <Input
                    id="title_fr"
                    value={formData.title_fr}
                    onChange={(e) => setFormData((p) => ({ ...p, title_fr: e.target.value }))}
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="title_en">{t('form.titleEn')}</Label>
                  <Input
                    id="title_en"
                    value={formData.title_en}
                    onChange={(e) => setFormData((p) => ({ ...p, title_en: e.target.value }))}
                    required
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="domain">{t('form.domain')}</Label>
                  <Input
                    id="domain"
                    value={formData.domain}
                    onChange={(e) => setFormData((p) => ({ ...p, domain: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="hours">{t('form.estimatedHours')}</Label>
                  <Input
                    id="hours"
                    type="number"
                    min="0"
                    value={formData.estimated_hours}
                    onChange={(e) => setFormData((p) => ({ ...p, estimated_hours: Number(e.target.value) }))}
                  />
                </div>
              </div>
              {formError && <p className="text-sm text-destructive">{formError}</p>}
              <div className="flex gap-2">
                <Button type="submit" size="sm" className="min-h-11" disabled={createMutation.isPending}>
                  {t('form.submit')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="min-h-11"
                  onClick={() => { setShowForm(false); setFormError(''); }}
                >
                  {t('form.cancel')}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {courses.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <p>{t('noCourses')}</p>
          <p className="text-sm mt-1">{t('createFirst')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {courses.map((course) => {
            const title = locale === 'fr' ? course.title_fr : course.title_en;
            return (
              <Card key={course.id}>
                <CardContent className="flex items-center justify-between py-4 px-4">
                  <div className="flex items-center gap-3 min-w-0">
                    {statusBadge(course.status)}
                    <div className="min-w-0">
                      <p className="font-medium truncate text-sm">{title}</p>
                      <p className="text-xs text-muted-foreground">{course.domain ?? '—'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-4">
                    {course.status === 'draft' && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="min-h-9"
                        onClick={() => publishMutation.mutate(course.id)}
                        disabled={publishMutation.isPending}
                      >
                        <Globe className="h-3 w-3 mr-1" />
                        {t('actions.publish')}
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
