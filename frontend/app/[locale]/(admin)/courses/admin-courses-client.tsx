'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { apiFetch } from '@/lib/api';
import { Plus, Globe, Clock } from 'lucide-react';

interface CourseData {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  domain: string | null;
  estimated_hours: number;
  module_count: number;
  status: string;
  created_at: string;
}

interface CreateCourseForm {
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
  domain: string;
  target_audience: string;
  estimated_hours: number;
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-amber-100 text-amber-800',
  published: 'bg-green-100 text-green-800',
  archived: 'bg-stone-100 text-stone-600',
};

export function AdminCoursesClient() {
  const t = useTranslations('AdminCourses');
  const locale = useLocale() as 'fr' | 'en';
  const [courses, setCourses] = useState<CourseData[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateCourseForm>({
    slug: '',
    title_fr: '',
    title_en: '',
    description_fr: '',
    description_en: '',
    domain: '',
    target_audience: '',
    estimated_hours: 20,
  });
  const [submitting, setSubmitting] = useState(false);
  const [publishing, setPublishing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchCourses = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiFetch<{ courses: CourseData[]; total: number }>(
        '/api/v1/admin/courses'
      );
      setCourses(data.courses);
    } catch {
      setError(t('error'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  const handleCreate = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch('/api/v1/admin/courses', {
        method: 'POST',
        body: JSON.stringify({ ...form, languages: ['fr', 'en'] }),
      });
      setShowCreate(false);
      setForm({
        slug: '',
        title_fr: '',
        title_en: '',
        description_fr: '',
        description_en: '',
        domain: '',
        target_audience: '',
        estimated_hours: 20,
      });
      fetchCourses();
    } catch {
      setError(t('error'));
    } finally {
      setSubmitting(false);
    }
  };

  const handlePublish = async (courseId: string) => {
    setPublishing(courseId);
    try {
      await apiFetch(`/api/v1/admin/courses/${courseId}/publish`, { method: 'POST' });
      fetchCourses();
    } catch {
      setError(t('publishError'));
    } finally {
      setPublishing(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 rounded-lg bg-stone-100 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex justify-end">
        <Button onClick={() => setShowCreate(!showCreate)} className="min-h-11">
          <Plus className="h-4 w-4 mr-2" />
          {t('createCourse')}
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('step1Title')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label htmlFor="slug">{t('slug')}</Label>
                <Input
                  id="slug"
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  placeholder="nutrition-communautaire"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="domain">{t('domain')}</Label>
                <Input
                  id="domain"
                  value={form.domain}
                  onChange={(e) => setForm({ ...form, domain: e.target.value })}
                  placeholder="Nutrition communautaire"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="title_fr">{t('titleFr')}</Label>
                <Input
                  id="title_fr"
                  value={form.title_fr}
                  onChange={(e) => setForm({ ...form, title_fr: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="title_en">{t('titleEn')}</Label>
                <Input
                  id="title_en"
                  value={form.title_en}
                  onChange={(e) => setForm({ ...form, title_en: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="description_fr">{t('descriptionFr')}</Label>
                <Input
                  id="description_fr"
                  value={form.description_fr}
                  onChange={(e) => setForm({ ...form, description_fr: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="description_en">{t('descriptionEn')}</Label>
                <Input
                  id="description_en"
                  value={form.description_en}
                  onChange={(e) => setForm({ ...form, description_en: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="target_audience">{t('targetAudience')}</Label>
                <Input
                  id="target_audience"
                  value={form.target_audience}
                  onChange={(e) => setForm({ ...form, target_audience: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="estimated_hours">{t('estimatedHours')}</Label>
                <Input
                  id="estimated_hours"
                  type="number"
                  min={1}
                  value={form.estimated_hours}
                  onChange={(e) =>
                    setForm({ ...form, estimated_hours: parseInt(e.target.value) || 20 })
                  }
                />
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <Button
                variant="outline"
                onClick={() => setShowCreate(false)}
                className="min-h-11"
              >
                {t('cancel')}
              </Button>
              <Button
                onClick={handleCreate}
                disabled={submitting || !form.slug || !form.title_fr || !form.title_en}
                className="min-h-11"
              >
                {submitting ? t('generating') : t('save')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {courses.length === 0 && !showCreate ? (
        <p className="text-center text-stone-500 py-12">{t('allCourses')}: 0</p>
      ) : (
        <div className="space-y-3">
          {courses.map((course) => {
            const title = locale === 'fr' ? course.title_fr : course.title_en;
            return (
              <Card key={course.id} className="border border-stone-200">
                <CardContent className="flex items-center gap-4 py-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[course.status] ?? ''}`}
                      >
                        {t(course.status as keyof typeof STATUS_COLORS)}
                      </span>
                      {course.domain && (
                        <Badge variant="outline" className="text-xs">
                          {course.domain}
                        </Badge>
                      )}
                    </div>
                    <p className="font-medium text-stone-900 truncate">{title}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-stone-500">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {course.estimated_hours}h
                      </span>
                      <span className="flex items-center gap-1">
                        <Globe className="h-3 w-3" />
                        {course.slug}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {course.status === 'draft' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handlePublish(course.id)}
                        disabled={publishing === course.id}
                        className="min-h-10"
                      >
                        {publishing === course.id ? t('generating') : t('publish')}
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
