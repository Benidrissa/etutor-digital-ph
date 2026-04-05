'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
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
  Database,
  ImageOff,
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
import { CourseWizardClient, loadWizardState } from '@/components/admin/course-wizard-client';
import { CoursePreassessmentSettings } from '@/components/admin/course-preassessment-settings';

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
  updated_at?: string;
  module_count?: number;
  indexation_task_id?: string | null;
  rag_collection_id?: string | null;
  preassessment_enabled?: boolean;
  preassessment_mandatory?: boolean;
}

type WizardStep = 'upload' | 'info' | 'generate' | 'index' | 'publish';

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

export function CoursesClient() {
  const t = useTranslations('AdminCourses');
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [editingCourse, setEditingCourse] = useState<AdminCourse | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardResumeCourseId, setWizardResumeCourseId] = useState<string | undefined>();
  const [wizardResumeStep, setWizardResumeStep] = useState<WizardStep | undefined>();
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [imagesIndexed, setImagesIndexed] = useState<number | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [generateTaskId, setGenerateTaskId] = useState<string | null>(null);
  const generatePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const saved = loadWizardState();
    if (saved) {
      setWizardResumeCourseId(saved.courseId);
      setWizardResumeStep(saved.step as WizardStep);
    }
  }, []);

  const { data: courses, isLoading, error, refetch } = useAdminCourses();

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

  const handlePublishIntent = useCallback(
    async (course: AdminCourse) => {
      setImagesIndexed(null);
      setPendingAction({ type: 'publish', course });
      if (course.rag_collection_id) {
        try {
          const data = await apiFetch<{ images_indexed?: number }>(
            `/api/v1/admin/courses/${course.id}/index-status`
          );
          setImagesIndexed(data.images_indexed ?? 0);
        } catch {
          setImagesIndexed(0);
        }
      } else {
        setImagesIndexed(0);
      }
    },
    []
  );

  const handleGenerateStructure = useCallback(
    async (course: AdminCourse) => {
      setGeneratingId(course.id);
      setGenerateTaskId(null);
      setActionError(null);
      setPendingAction(null);
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
        const data = await res.json() as { task_id?: string; status?: string };
        if (data.task_id) {
          setGenerateTaskId(data.task_id);
        } else {
          setGeneratingId(null);
          queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
        }
      } catch {
        setActionError(t('generateError'));
        setGeneratingId(null);
      }
    },
    [router, locale, queryClient, t]
  );

  useEffect(() => {
    if (!generatingId || !generateTaskId) return;

    let token: string | null = null;
    authClient.getValidToken().then((t) => { token = t; }).catch(() => {});

    const poll = async () => {
      try {
        const currentToken = token ?? await authClient.getValidToken();
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/admin/courses/${generatingId}/generate-status?task_id=${generateTaskId}`,
          { headers: { Authorization: `Bearer ${currentToken}` } }
        );
        if (!res.ok) {
          generatePollRef.current = setTimeout(poll, 5000);
          return;
        }
        const status = await res.json() as {
          task?: { state: string };
        };

        if (
          status.task?.state === 'FAILURE' ||
          status.task?.state === 'REVOKED'
        ) {
          setActionError(t('generateError'));
          setGeneratingId(null);
          setGenerateTaskId(null);
          return;
        }

        if (status.task?.state === 'SUCCESS') {
          setGeneratingId(null);
          setGenerateTaskId(null);
          queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
          return;
        }

        generatePollRef.current = setTimeout(poll, 3000);
      } catch {
        generatePollRef.current = setTimeout(poll, 5000);
      }
    };

    generatePollRef.current = setTimeout(poll, 2000);
    return () => {
      if (generatePollRef.current) clearTimeout(generatePollRef.current);
    };
  }, [generatingId, generateTaskId, queryClient, t]);

  const handleFormSaved = () => {
    setFormOpen(false);
    setEditingCourse(null);
    queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
  };

  const openWizardFresh = () => {
    setWizardResumeCourseId(undefined);
    setWizardResumeStep(undefined);
    setWizardOpen(true);
  };

  const openWizardResume = () => {
    setWizardOpen(true);
  };

  const handleWizardClose = () => {
    setWizardOpen(false);
    const saved = loadWizardState();
    if (saved) {
      setWizardResumeCourseId(saved.courseId);
      setWizardResumeStep(saved.step as WizardStep);
    } else {
      setWizardResumeCourseId(undefined);
      setWizardResumeStep(undefined);
    }
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
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-sm text-muted-foreground">
            {t('courseCount', { count: courses?.length ?? 0 })}
          </p>
          <div className="flex items-center gap-2">
            {wizardResumeCourseId && (
              <Button
                variant="outline"
                onClick={openWizardResume}
                className="gap-2 min-h-11 text-amber-700 border-amber-300 hover:bg-amber-50"
              >
                <Database className="h-4 w-4 animate-pulse" aria-hidden="true" />
                {t('wizard.resumeFrom')}
              </Button>
            )}
            <Button
              onClick={openWizardFresh}
              className="gap-2 min-h-11"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t('createCourse')}
            </Button>
          </div>
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
                resumeCourseId={wizardResumeCourseId}
                onPublish={handlePublishIntent}
                onArchive={(c) => setPendingAction({ type: 'archive', course: c })}
                onGenerateStructure={(c) => setPendingAction({ type: 'generate', course: c })}
                onEdit={(c) => { setEditingCourse(c); setFormOpen(true); }}
                onResumeWizard={() => { setWizardResumeCourseId(course.id); setWizardResumeStep(wizardResumeStep); openWizardResume(); }}
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
          onCourseCreated={() => {
            setWizardOpen(false);
            setWizardResumeCourseId(undefined);
            setWizardResumeStep(undefined);
            queryClient.invalidateQueries({ queryKey: ['admin', 'courses'] });
          }}
          resumeCourseId={wizardResumeCourseId}
          resumeStep={wizardResumeStep}
        />
      )}

      <AlertDialog
        open={pendingAction !== null && pendingAction.type !== 'generate'}
        onOpenChange={(open) => !open && setPendingAction(null)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          <AlertDialogDescription>{confirmDesc}</AlertDialogDescription>
          {pendingAction?.type === 'publish' && imagesIndexed === 0 && (
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200" role="alert">
              <ImageOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{t('imagesNotIndexedWarning')}</span>
            </div>
          )}
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
  resumeCourseId,
  onPublish,
  onArchive,
  onGenerateStructure,
  onEdit,
  onResumeWizard,
}: {
  course: AdminCourse;
  generatingId: string | null;
  resumeCourseId?: string;
  onPublish: (c: AdminCourse) => void;
  onArchive: (c: AdminCourse) => void;
  onGenerateStructure: (c: AdminCourse) => void;
  onEdit: (c: AdminCourse) => void;
  onResumeWizard: () => void;
}) {
  const t = useTranslations('AdminCourses');
  const locale = useLocale();

  const title = locale === 'fr' ? course.title_fr : course.title_en;

  const statusVariant =
    course.status === 'published'
      ? 'default'
      : course.status === 'archived'
        ? 'secondary'
        : 'outline';

  const isGenerating = generatingId === course.id;
  const isIndexingInProgress = resumeCourseId === course.id;

  return (
    <Card className={`p-4 ${isIndexingInProgress ? 'border-amber-300 dark:border-amber-700' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <button
          className="flex flex-col gap-1 text-left min-w-0 flex-1"
          onClick={isIndexingInProgress ? onResumeWizard : () => onEdit(course)}
          aria-label={isIndexingInProgress ? t('wizard.resumeFrom') : t('editCourse')}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{title}</span>
            <Badge variant={statusVariant}>{t(`status.${course.status}`)}</Badge>
            {isIndexingInProgress && (
              <Badge className="gap-1 bg-amber-100 text-amber-800 border-amber-300 hover:bg-amber-100 dark:bg-amber-900 dark:text-amber-200">
                <Database className="h-3 w-3 animate-pulse" aria-hidden="true" />
                {t('wizard.indexingBadge')}
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
      <CoursePreassessmentSettings
        courseId={course.id}
        ragIndexed={!!course.rag_collection_id}
        preassessmentEnabled={!!course.preassessment_enabled}
        preassessmentMandatory={!!course.preassessment_mandatory}
        courseTitleFr={course.title_fr}
        courseTitleEn={course.title_en}
      />
    </Card>
  );
}
