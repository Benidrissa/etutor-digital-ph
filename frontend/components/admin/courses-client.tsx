'use client';

import { useState, useCallback, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  MoreVertical,
  Globe,
  Archive,
  Sparkles,
  Loader2,
  AlertCircle,
  BookOpen,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import { apiFetch } from '@/lib/api';
import { authClient, AuthError } from '@/lib/auth';
import { CourseForm } from '@/components/admin/course-form';
import { CourseWizardClient } from '@/components/admin/course-wizard-client';
import type { CourseWizardClientProps } from '@/components/admin/course-wizard-client';

const WIZARD_STORAGE_KEY = 'wizard_state';

interface WizardPersistedState {
  courseId: string;
  step: CourseWizardClientProps['resumeStep'];
}

export interface AdminCourse {
  id: string;
  title_fr: string;
  title_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  estimated_hours: number;
  cover_image_url: string | null;
  status: 'draft' | 'published' | 'archived';
  created_at: string;
  updated_at: string;
  module_count?: number;
  indexation_task_id?: string | null;
}

interface IndexStatusResponse {
  indexed: boolean;
  chunks_indexed: number;
  indexation_task_id?: string;
  task?: { state: string };
}

type PendingAction =
  | { type: 'publish'; course: AdminCourse }
  | { type: 'archive'; course: AdminCourse }
  | { type: 'generate'; course: AdminCourse };

function useAdminCourses() {
  return useQuery<AdminCourse[]>({
    queryKey: ['admin', 'courses'],
    queryFn: () => apiFetch<AdminCourse[]>('/api/v1/admin/courses'),
  });
}

function useIndexStatus(courseId: string | null) {
  return useQuery<IndexStatusResponse>({
    queryKey: ['admin', 'course-index-status', courseId],
    queryFn: () => apiFetch<IndexStatusResponse>(`/api/v1/admin/courses/${courseId}/index-status`),
    enabled: !!courseId,
    refetchInterval: 5000,
  });
}

export function CoursesClient() {
  const t = useTranslations('AdminCourses');
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [editingCourse, setEditingCourse] = useState<AdminCourse | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardResumeProps, setWizardResumeProps] = useState<{
    courseId?: string;
    step?: CourseWizardClientProps['resumeStep'];
  }>({});
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  const { data: courses, isLoading, error, refetch } = useAdminCourses();

  useEffect(() => {
    try {
      const raw = localStorage.getItem(WIZARD_STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as WizardPersistedState;
        if (saved.courseId && saved.step) {
          setWizardResumeProps({ courseId: saved.courseId, step: saved.step });
        }
      }
    } catch {
    }
  }, []);

  const publishMutation = useMutation({
    mutationFn: (courseId: string) =>
      apiFetch(`/api/v1/admin/courses/${courseId}/publish`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: () => setActionError(t('actionError')),
  });

  const archiveMutation = useMutation({
    mutationFn: (courseId: string) =>
      apiFetch(`/api/v1/admin/courses/${courseId}/archive`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: () => setActionError(t('actionError')),
  });

  const handleConfirmAction = () => {
    if (!pendingAction) return;
    if (pendingAction.type === 'publish') {
      publishMutation.mutate(pendingAction.course.id);
    } else if (pendingAction.type === 'archive') {
      archiveMutation.mutate(pendingAction.course.id);
    }
  };

  const handleGenerateStructure = useCallback(
    async (course: AdminCourse) => {
      setGeneratingId(course.id);
      setActionError(null);
      try {
        let token: string;
        try {
          token = await authClient.getValidToken();
        } catch (err) {
          if (err instanceof AuthError && err.status === 401) {
            router.push(`/${locale}/login`);
            return;
          }
          throw err;
        }
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/admin/courses/${course.id}/generate-structure`,
          {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${token}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ estimated_hours: course.estimated_hours || 20 }),
          }
        );
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
      } catch {
        setActionError(t('generateError'));
      } finally {
        setGeneratingId(null);
        setPendingAction(null);
      }
    },
    [router, locale, queryClient, t]
  );

  const handleFormSaved = () => {
    setFormOpen(false);
    setEditingCourse(null);
    queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
  };

  const handleOpenWizard = () => {
    setWizardResumeProps({});
    setWizardOpen(true);
  };

  const handleResumeWizard = (courseId: string) => {
    setWizardResumeProps({ courseId, step: 'index' });
    setWizardOpen(true);
  };

  const handleWizardClose = () => {
    setWizardOpen(false);
    setWizardResumeProps({});
  };

  const handleWizardCourseCreated = () => {
    setWizardOpen(false);
    setWizardResumeProps({});
    queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
  };

  const confirmTitle =
    pendingAction?.type === 'publish'
      ? t('confirmPublish')
      : pendingAction?.type === 'archive'
        ? t('confirmArchive')
        : t('confirmGenerate');

  const confirmDesc =
    pendingAction?.type === 'publish'
      ? t('confirmPublishDesc')
      : pendingAction?.type === 'archive'
        ? t('confirmArchiveDesc')
        : t('confirmGenerateDesc');

  const inProgressCourseIds = new Set<string>();
  if (wizardResumeProps.courseId) {
    inProgressCourseIds.add(wizardResumeProps.courseId);
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" />
        <p className="text-sm text-muted-foreground">{t('errorLoading')}</p>
        <Button variant="outline" onClick={() => refetch()}>
          {t('retry')}
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {t('courseCount', { count: courses?.length ?? 0 })}
          </p>
          <Button
            onClick={handleOpenWizard}
            className="gap-2 min-h-11"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('createCourse')}
          </Button>
        </div>

        {actionError && (
          <p className="text-sm text-destructive" role="alert">{actionError}</p>
        )}

        {!courses || courses.length === 0 ? (
          <div className="py-16 text-center">
            <BookOpen className="h-12 w-12 text-muted-foreground mx-auto mb-4" aria-hidden="true" />
            <p className="font-medium text-muted-foreground">{t('noCourses')}</p>
            <p className="text-sm text-muted-foreground mt-1">{t('noCoursesDescription')}</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {courses.map((course) => (
              <CourseRow
                key={course.id}
                course={course}
                generatingId={generatingId}
                isIndexingInProgress={
                  wizardResumeProps.courseId === course.id ||
                  !!course.indexation_task_id
                }
                onPublish={(c) => setPendingAction({ type: 'publish', course: c })}
                onArchive={(c) => setPendingAction({ type: 'archive', course: c })}
                onGenerateStructure={(c) => setPendingAction({ type: 'generate', course: c })}
                onEdit={(c) => { setEditingCourse(c); setFormOpen(true); }}
                onResumeIndexing={(c) => handleResumeWizard(c.id)}
              />
            ))}
          </div>
        )}
      </div>

      {formOpen && (
        <CourseForm
          course={editingCourse}
          onClose={() => { setFormOpen(false); setEditingCourse(null); }}
          onSaved={handleFormSaved}
        />
      )}

      {wizardOpen && (
        <CourseWizardClient
          onClose={handleWizardClose}
          onCourseCreated={handleWizardCourseCreated}
          resumeCourseId={wizardResumeProps.courseId}
          resumeStep={wizardResumeProps.step}
        />
      )}

      <AlertDialog
        open={pendingAction !== null && pendingAction.type !== 'generate'}
        onOpenChange={(open) => !open && setPendingAction(null)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          <AlertDialogDescription>{confirmDesc}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setPendingAction(null)}>
              {t('cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmAction}
              disabled={publishMutation.isPending || archiveMutation.isPending}
            >
              {t('confirm')}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={pendingAction?.type === 'generate'}
        onOpenChange={(open) => !open && setPendingAction(null)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          <AlertDialogDescription>{confirmDesc}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setPendingAction(null)}>
              {t('cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingAction?.type === 'generate') {
                  handleGenerateStructure(pendingAction.course);
                }
              }}
              disabled={generatingId !== null}
            >
              {generatingId !== null ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                t('confirm')
              )}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function CourseRow({
  course,
  generatingId,
  isIndexingInProgress,
  onPublish,
  onArchive,
  onGenerateStructure,
  onEdit,
  onResumeIndexing,
}: {
  course: AdminCourse;
  generatingId: string | null;
  isIndexingInProgress: boolean;
  onPublish: (c: AdminCourse) => void;
  onArchive: (c: AdminCourse) => void;
  onGenerateStructure: (c: AdminCourse) => void;
  onEdit: (c: AdminCourse) => void;
  onResumeIndexing: (c: AdminCourse) => void;
}) {
  const t = useTranslations('AdminCourses');
  const locale = useLocale();

  const { data: indexStatus } = useIndexStatus(
    isIndexingInProgress ? course.id : null
  );

  const isRunning =
    isIndexingInProgress &&
    indexStatus?.task?.state !== 'SUCCESS' &&
    indexStatus?.task?.state !== 'FAILURE' &&
    !indexStatus?.indexed;

  const title = locale === 'fr' ? course.title_fr : course.title_en;

  const statusVariant =
    course.status === 'published'
      ? 'default'
      : course.status === 'archived'
        ? 'secondary'
        : 'outline';

  const isGenerating = generatingId === course.id;

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <button
          className="flex flex-col gap-1 text-left min-w-0 flex-1"
          onClick={() => onEdit(course)}
          aria-label={t('editCourse')}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{title}</span>
            <Badge variant={statusVariant}>{t(`status.${course.status}`)}</Badge>
            {isRunning && (
              <Badge className="bg-amber-100 text-amber-700 border-amber-300 gap-1">
                <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
                {t('indexingBadge')}
              </Badge>
            )}
          </div>
          {(course.course_domain?.length > 0 || course.course_level?.length > 0) && (
            <div className="flex gap-1 flex-wrap">
              {course.course_domain?.map((d) => (
                <span key={d} className="text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-1.5 py-0.5">
                  {d.replace(/_/g, ' ')}
                </span>
              ))}
              {course.course_level?.map((l) => (
                <span key={l} className="text-[10px] font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-full px-1.5 py-0.5">
                  {l}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <span className="text-xs text-muted-foreground">
              {t('estimatedHours', { hours: course.estimated_hours })}
            </span>
            {course.module_count !== undefined && (
              <span className="text-xs text-muted-foreground">
                {t('moduleCount', { count: course.module_count })}
              </span>
            )}
          </div>
        </button>

        <div className="flex items-center gap-2 shrink-0">
          {isRunning && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 min-h-11 hidden sm:flex text-amber-700 border-amber-300 hover:bg-amber-50"
              onClick={() => onResumeIndexing(course)}
              aria-label={t('resumeCreation')}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              <span className="hidden md:inline">{t('resumeCreation')}</span>
            </Button>
          )}

          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 min-h-11 hidden sm:flex"
            onClick={() => onGenerateStructure(course)}
            disabled={isGenerating}
            aria-label={t('generateStructure')}
          >
            {isGenerating ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            )}
            <span className="hidden md:inline">{t('generateStructure')}</span>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="sm"
                  className="min-h-11 min-w-11 p-2 shrink-0"
                  aria-label={t('actions')}
                />
              }
            >
              <MoreVertical className="h-4 w-4" aria-hidden="true" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onEdit(course)}>
                <BookOpen className="mr-2 h-4 w-4" />
                {t('editCourse')}
              </DropdownMenuItem>
              {isRunning && (
                <DropdownMenuItem onClick={() => onResumeIndexing(course)}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {t('resumeCreation')}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                className="sm:hidden"
                onClick={() => onGenerateStructure(course)}
                disabled={isGenerating}
              >
                <Sparkles className="mr-2 h-4 w-4" />
                {t('generateStructure')}
              </DropdownMenuItem>
              {course.status !== 'published' && (
                <DropdownMenuItem onClick={() => onPublish(course)}>
                  <Globe className="mr-2 h-4 w-4" />
                  {t('publish')}
                </DropdownMenuItem>
              )}
              {course.status !== 'archived' && (
                <DropdownMenuItem
                  onClick={() => onArchive(course)}
                  className="text-destructive"
                >
                  <Archive className="mr-2 h-4 w-4" />
                  {t('archive')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </Card>
  );
}
