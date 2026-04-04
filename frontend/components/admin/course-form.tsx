'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { apiFetch } from '@/lib/api';
import { authClient, AuthError } from '@/lib/auth';
import type { AdminCourse } from './courses-client';

interface CourseFormProps {
  course: AdminCourse | null;
  onClose: () => void;
  onSaved: () => void;
}

interface CoursePayload {
  title_fr: string;
  title_en: string;
  domain: string;
  target_audience: string;
  estimated_hours: number;
  cover_image_url: string;
}

export function CourseForm({ course, onClose, onSaved }: CourseFormProps) {
  const t = useTranslations('AdminCourses');
  const router = useRouter();

  const [titleFr, setTitleFr] = useState(course?.title_fr ?? '');
  const [titleEn, setTitleEn] = useState(course?.title_en ?? '');
  const [domain, setDomain] = useState(course?.domain ?? '');
  const [targetAudience, setTargetAudience] = useState(course?.target_audience ?? '');
  const [estimatedHours, setEstimatedHours] = useState<string>(
    course ? String(course.estimated_hours) : ''
  );
  const [coverImageUrl, setCoverImageUrl] = useState(course?.cover_image_url ?? '');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const validate = () => {
    const errors: Record<string, string> = {};
    if (!titleFr.trim()) errors.titleFr = t('fieldRequired');
    if (!titleEn.trim()) errors.titleEn = t('fieldRequired');
    const hours = parseFloat(estimatedHours);
    if (!estimatedHours || isNaN(hours) || hours <= 0) {
      errors.estimatedHours = t('fieldInvalidHours');
    }
    return errors;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    setIsSaving(true);

    const payload: CoursePayload = {
      title_fr: titleFr.trim(),
      title_en: titleEn.trim(),
      domain: domain.trim(),
      target_audience: targetAudience.trim(),
      estimated_hours: parseFloat(estimatedHours),
      cover_image_url: coverImageUrl.trim(),
    };

    try {
      let token: string;
      try {
        token = await authClient.getValidToken();
      } catch (err) {
        if (err instanceof AuthError && err.status === 401) {
          router.push('/login');
          return;
        }
        throw err;
      }

      const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

      if (course) {
        await fetch(`${API_BASE}/api/v1/admin/courses/${course.id}`, {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        }).then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        });
      } else {
        await apiFetch('/api/v1/admin/courses', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }

      onSaved();
    } catch {
      setSaveError(t('saveError'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label={course ? t('editCourse') : t('createCourse')}
    >
      <div
        className="fixed inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-lg bg-background rounded-t-2xl sm:rounded-2xl shadow-xl flex flex-col max-h-[90dvh]">
        <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b shrink-0">
          <h2 className="text-base font-semibold">
            {course ? t('editCourse') : t('createCourse')}
          </h2>
          <Button
            variant="ghost"
            size="sm"
            className="min-h-11 min-w-11 p-2"
            onClick={onClose}
            aria-label={t('close')}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0 overflow-y-auto p-4 gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-title-fr">{t('titleFr')}</Label>
            <Input
              id="course-title-fr"
              value={titleFr}
              onChange={(e) => setTitleFr(e.target.value)}
              placeholder={t('titleFrPlaceholder')}
              className="min-h-11"
              aria-describedby={fieldErrors.titleFr ? 'error-title-fr' : undefined}
              aria-invalid={!!fieldErrors.titleFr}
            />
            {fieldErrors.titleFr && (
              <p id="error-title-fr" className="text-xs text-destructive" role="alert">
                {fieldErrors.titleFr}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-title-en">{t('titleEn')}</Label>
            <Input
              id="course-title-en"
              value={titleEn}
              onChange={(e) => setTitleEn(e.target.value)}
              placeholder={t('titleEnPlaceholder')}
              className="min-h-11"
              aria-describedby={fieldErrors.titleEn ? 'error-title-en' : undefined}
              aria-invalid={!!fieldErrors.titleEn}
            />
            {fieldErrors.titleEn && (
              <p id="error-title-en" className="text-xs text-destructive" role="alert">
                {fieldErrors.titleEn}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-domain">{t('domain')}</Label>
            <Input
              id="course-domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder={t('domainPlaceholder')}
              className="min-h-11"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-audience">{t('targetAudience')}</Label>
            <Input
              id="course-audience"
              value={targetAudience}
              onChange={(e) => setTargetAudience(e.target.value)}
              placeholder={t('targetAudiencePlaceholder')}
              className="min-h-11"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-hours">{t('estimatedHoursField')}</Label>
            <Input
              id="course-hours"
              type="number"
              min="1"
              step="0.5"
              value={estimatedHours}
              onChange={(e) => setEstimatedHours(e.target.value)}
              placeholder="40"
              className="min-h-11"
              aria-describedby={fieldErrors.estimatedHours ? 'error-hours' : undefined}
              aria-invalid={!!fieldErrors.estimatedHours}
            />
            {fieldErrors.estimatedHours && (
              <p id="error-hours" className="text-xs text-destructive" role="alert">
                {fieldErrors.estimatedHours}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="course-cover">{t('coverImageUrl')}</Label>
            <Input
              id="course-cover"
              value={coverImageUrl}
              onChange={(e) => setCoverImageUrl(e.target.value)}
              placeholder="https://..."
              className="min-h-11"
            />
          </div>

          {saveError && (
            <p className="text-sm text-destructive" role="alert">{saveError}</p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="min-h-11"
            >
              {t('cancel')}
            </Button>
            <Button
              type="submit"
              disabled={isSaving}
              className="min-h-11 gap-2"
            >
              {isSaving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {t('save')}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
