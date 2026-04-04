'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Loader2, AlertCircle, BookOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import { apiFetch } from '@/lib/api';
import { ExpertCourseCard, type ExpertCourse } from '@/components/expert/course-card';

type PendingAction =
  | { type: 'publish'; course: ExpertCourse }
  | { type: 'unpublish'; course: ExpertCourse }
  | { type: 'delete'; course: ExpertCourse };

function useExpertCourses() {
  return useQuery<ExpertCourse[]>({
    queryKey: ['expert', 'courses'],
    queryFn: () => apiFetch<ExpertCourse[]>('/api/v1/expert/courses'),
  });
}

export function ExpertCoursesClient() {
  const t = useTranslations('ExpertCourses');
  const locale = useLocale();
  const queryClient = useQueryClient();

  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: courses, isLoading, error, refetch } = useExpertCourses();

  const publishMutation = useMutation({
    mutationFn: (courseId: string) =>
      apiFetch(`/api/v1/expert/courses/${courseId}/publish`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: () => setActionError(t('actionError')),
  });

  const unpublishMutation = useMutation({
    mutationFn: (courseId: string) =>
      apiFetch(`/api/v1/expert/courses/${courseId}/unpublish`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: () => setActionError(t('actionError')),
  });

  const deleteMutation = useMutation({
    mutationFn: (courseId: string) =>
      apiFetch(`/api/v1/expert/courses/${courseId}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: () => setActionError(t('actionError')),
  });

  const handleConfirmAction = () => {
    if (!pendingAction) return;
    if (pendingAction.type === 'publish') {
      publishMutation.mutate(pendingAction.course.id);
    } else if (pendingAction.type === 'unpublish') {
      unpublishMutation.mutate(pendingAction.course.id);
    } else if (pendingAction.type === 'delete') {
      deleteMutation.mutate(pendingAction.course.id);
    }
  };

  const isPending =
    publishMutation.isPending || unpublishMutation.isPending || deleteMutation.isPending;

  const confirmTitle =
    pendingAction?.type === 'publish'
      ? t('confirmPublish')
      : pendingAction?.type === 'unpublish'
        ? t('confirmUnpublish')
        : t('confirmDelete');

  const confirmDesc =
    pendingAction?.type === 'publish'
      ? t('confirmPublishDesc')
      : pendingAction?.type === 'unpublish'
        ? t('confirmUnpublishDesc')
        : t('confirmDeleteDesc');

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
          <Button asChild className="gap-2 min-h-11">
            <Link href={`/${locale}/expert/courses/new`}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t('createCourse')}
            </Link>
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
            <Button asChild className="mt-4 gap-2 min-h-11">
              <Link href={`/${locale}/expert/courses/new`}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                {t('createCourse')}
              </Link>
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {courses.map((course) => (
              <ExpertCourseCard
                key={course.id}
                course={course}
                onPublish={(c) => setPendingAction({ type: 'publish', course: c })}
                onUnpublish={(c) => setPendingAction({ type: 'unpublish', course: c })}
                onDelete={(c) => setPendingAction({ type: 'delete', course: c })}
              />
            ))}
          </div>
        )}
      </div>

      <AlertDialog
        open={pendingAction !== null}
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
              disabled={isPending}
              className={pendingAction?.type === 'delete' ? 'bg-destructive hover:bg-destructive/90' : ''}
            >
              {isPending ? (
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
