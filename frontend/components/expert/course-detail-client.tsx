'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Upload,
  FileText,
  Trash2,
  Database,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Globe,
  GlobeLock,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { apiFetch, API_BASE } from '@/lib/api';
import { authClient } from '@/lib/auth';
import type { ExpertCourse } from '@/components/expert/course-card';

interface CourseModule {
  id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
  content_status?: 'generated' | 'pending';
}

interface CourseResource {
  name: string;
  size_bytes: number;
  uploaded_at: string;
}

interface CourseDetailData extends ExpertCourse {
  modules?: CourseModule[];
  resources?: CourseResource[];
  description_fr?: string;
  description_en?: string;
  chunks_indexed?: number;
  is_indexed?: boolean;
  task_id?: string;
}

interface CourseDetailClientProps {
  courseId: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ExpertCourseDetailClient({ courseId }: CourseDetailClientProps) {
  const t = useTranslations('ExpertCourses');
  const locale = useLocale();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [isDragOver, setIsDragOver] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexTaskId, setIndexTaskId] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<{
    indexed: boolean;
    chunks_indexed: number;
    task_state?: string;
  } | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [showUnpublishDialog, setShowUnpublishDialog] = useState(false);
  const [isSavingMetadata, setIsSavingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const [metadataSaved, setMetadataSaved] = useState(false);

  const { data: course, isLoading, error } = useQuery<CourseDetailData>({
    queryKey: ['expert', 'course', courseId],
    queryFn: () => apiFetch<CourseDetailData>(`/api/v1/expert/courses/${courseId}`),
  });

  const [localTitle_fr, setLocalTitle_fr] = useState('');
  const [localTitle_en, setLocalTitle_en] = useState('');
  const [localDesc_fr, setLocalDesc_fr] = useState('');
  const [localDesc_en, setLocalDesc_en] = useState('');
  const [localHours, setLocalHours] = useState(20);
  const [localPrice, setLocalPrice] = useState(0);

  useEffect(() => {
    if (course) {
      setLocalTitle_fr(course.title_fr);
      setLocalTitle_en(course.title_en);
      setLocalDesc_fr(course.description_fr ?? '');
      setLocalDesc_en(course.description_en ?? '');
      setLocalHours(course.estimated_hours);
      setLocalPrice(course.price_credits ?? 0);
      if (course.is_indexed) {
        setIndexStatus({
          indexed: true,
          chunks_indexed: course.chunks_indexed ?? 0,
        });
      }
    }
  }, [course]);

  const publishMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/expert/courses/${courseId}/publish`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['expert', 'course', courseId] });
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setShowPublishDialog(false);
    },
    onError: () => setActionError(t('errors.publish')),
  });

  const unpublishMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/expert/courses/${courseId}/unpublish`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['expert', 'course', courseId] });
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setShowUnpublishDialog(false);
    },
    onError: () => setActionError(t('errors.unpublish')),
  });

  const getAuthHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await authClient.getValidToken();
    return { Authorization: `Bearer ${token}` };
  }, []);

  const handleUpload = useCallback(
    async (files: File[]) => {
      const pdfs = files.filter((f) => f.type === 'application/pdf');
      if (!pdfs.length) return;
      setUploadError(null);

      for (const file of pdfs) {
        setUploadingFiles((prev) => [...prev, file.name]);
        try {
          const formData = new FormData();
          formData.append('file', file);
          const headers = await getAuthHeaders();
          const res = await fetch(`${API_BASE}/api/v1/expert/courses/${courseId}/resources`, {
            method: 'POST',
            headers,
            body: formData,
          });
          if (!res.ok) throw new Error();
          queryClient.invalidateQueries({ queryKey: ['expert', 'course', courseId] });
        } catch {
          setUploadError(t('errors.index'));
        } finally {
          setUploadingFiles((prev) => prev.filter((n) => n !== file.name));
        }
      }
    },
    [courseId, getAuthHeaders, queryClient, t]
  );

  const handleRemoveResource = useCallback(
    async (name: string) => {
      try {
        const headers = await getAuthHeaders();
        await fetch(
          `${API_BASE}/api/v1/expert/courses/${courseId}/resources/${encodeURIComponent(name)}`,
          { method: 'DELETE', headers }
        );
        queryClient.invalidateQueries({ queryKey: ['expert', 'course', courseId] });
      } catch {
        setActionError(t('actionError'));
      }
    },
    [courseId, getAuthHeaders, queryClient, t]
  );

  const startIndexation = useCallback(async () => {
    setIsIndexing(true);
    setIndexError(null);
    try {
      const result = await apiFetch<{ task_id: string; status: string }>(
        `/api/v1/expert/courses/${courseId}/index-resources`,
        { method: 'POST' }
      );
      setIndexTaskId(result.task_id);
    } catch {
      setIndexError(t('indexError'));
      setIsIndexing(false);
    }
  }, [courseId, t]);

  useEffect(() => {
    if (!isIndexing) return;

    const poll = async () => {
      try {
        const params = indexTaskId ? `?task_id=${indexTaskId}` : '';
        const status = await apiFetch<{
          indexed: boolean;
          chunks_indexed: number;
          task?: { state: string };
        }>(`/api/v1/expert/courses/${courseId}/index-status${params}`);

        setIndexStatus({
          indexed: status.indexed,
          chunks_indexed: status.chunks_indexed,
          task_state: status.task?.state,
        });

        if (status.indexed && status.chunks_indexed > 0) {
          setIsIndexing(false);
          return;
        }

        if (status.task?.state === 'FAILURE' || status.task?.state === 'REVOKED') {
          setIndexError(t('indexError'));
          setIsIndexing(false);
          return;
        }

        pollRef.current = setTimeout(poll, 3000);
      } catch {
        pollRef.current = setTimeout(poll, 5000);
      }
    };

    pollRef.current = setTimeout(poll, 2000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [isIndexing, indexTaskId, courseId, t]);

  const handleSaveMetadata = useCallback(async () => {
    setIsSavingMetadata(true);
    setMetadataError(null);
    try {
      await apiFetch(`/api/v1/expert/courses/${courseId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title_fr: localTitle_fr,
          title_en: localTitle_en,
          description_fr: localDesc_fr || undefined,
          description_en: localDesc_en || undefined,
          estimated_hours: localHours,
          price_credits: localPrice,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['expert', 'course', courseId] });
      queryClient.invalidateQueries({ queryKey: ['expert', 'courses'] });
      setMetadataSaved(true);
      setTimeout(() => setMetadataSaved(false), 2000);
    } catch {
      setMetadataError(t('saveError'));
    } finally {
      setIsSavingMetadata(false);
    }
  }, [courseId, localTitle_fr, localTitle_en, localDesc_fr, localDesc_en, localHours, localPrice, queryClient, t]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" />
        <p className="text-sm text-muted-foreground">{t('errorLoading')}</p>
      </div>
    );
  }

  const title = locale === 'fr' ? course.title_fr : course.title_en;
  const isPublished = course.status === 'published';
  const hasModules = (course.modules?.length ?? 0) > 0;

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 max-w-3xl mx-auto w-full">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild className="min-h-11 min-w-11 p-2">
          <Link href={`/${locale}/expert/courses`} aria-label={t('backToList')}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold truncate">{title}</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <Badge variant={isPublished ? 'default' : 'outline'}>
              {t(`status.${course.status}`)}
            </Badge>
          </div>
        </div>
      </div>

      {actionError && (
        <p className="text-sm text-destructive" role="alert">{actionError}</p>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <CardTitle className="text-base">
            {t('publish')} / {t('unpublish')}
          </CardTitle>
          <Button
            variant={isPublished ? 'outline' : 'default'}
            size="sm"
            className="min-h-11 gap-2 shrink-0"
            disabled={!hasModules || publishMutation.isPending || unpublishMutation.isPending}
            onClick={() => {
              if (isPublished) setShowUnpublishDialog(true);
              else setShowPublishDialog(true);
            }}
          >
            {isPublished ? (
              <><GlobeLock className="h-4 w-4" />{t('unpublish')}</>
            ) : (
              <><Globe className="h-4 w-4" />{t('publish')}</>
            )}
          </Button>
        </CardHeader>
        {!hasModules && (
          <CardContent>
            <p className="text-xs text-muted-foreground">{t('publishRequirements')}</p>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('edit')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="edit_title_fr">{t('titleFr')} *</Label>
            <Input
              id="edit_title_fr"
              value={localTitle_fr}
              onChange={(e) => setLocalTitle_fr(e.target.value)}
              className="min-h-11"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_title_en">{t('titleEn')} *</Label>
            <Input
              id="edit_title_en"
              value={localTitle_en}
              onChange={(e) => setLocalTitle_en(e.target.value)}
              className="min-h-11"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_desc_fr">{t('descriptionFr')}</Label>
            <Textarea
              id="edit_desc_fr"
              value={localDesc_fr}
              onChange={(e) => setLocalDesc_fr(e.target.value)}
              rows={3}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_desc_en">{t('descriptionEn')}</Label>
            <Textarea
              id="edit_desc_en"
              value={localDesc_en}
              onChange={(e) => setLocalDesc_en(e.target.value)}
              rows={3}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="edit_hours">{t('estimatedHoursField')}</Label>
              <Input
                id="edit_hours"
                type="number"
                min={1}
                max={500}
                value={localHours}
                onChange={(e) => setLocalHours(parseInt(e.target.value) || 20)}
                className="min-h-11"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit_price">{t('price')}</Label>
              <Input
                id="edit_price"
                type="number"
                min={0}
                value={localPrice}
                onChange={(e) => setLocalPrice(parseInt(e.target.value) || 0)}
                className="min-h-11"
              />
            </div>
          </div>

          {metadataError && (
            <p className="text-xs text-destructive">{metadataError}</p>
          )}
          {metadataSaved && (
            <p className="text-xs text-green-600 flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {t('save')}
            </p>
          )}

          <Button
            onClick={handleSaveMetadata}
            disabled={isSavingMetadata || !localTitle_fr.trim() || !localTitle_en.trim()}
            className="w-full min-h-11"
          >
            {isSavingMetadata ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            {t('save')}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('modulesStatus')}</CardTitle>
        </CardHeader>
        <CardContent>
          {!course.modules || course.modules.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('wizard.generate.noModules')}</p>
          ) : (
            <div className="space-y-2">
              {course.modules.map((m) => (
                <div
                  key={m.id}
                  className="flex items-center gap-3 rounded-lg border bg-card p-3"
                >
                  <Badge variant="outline" className="shrink-0 text-xs">
                    M{m.module_number}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm font-medium">
                      {locale === 'fr' ? m.title_fr : m.title_en}
                    </p>
                  </div>
                  <Badge
                    variant={m.content_status === 'generated' ? 'default' : 'outline'}
                    className="text-xs shrink-0"
                  >
                    {m.content_status === 'generated'
                      ? t('moduleGenerated')
                      : t('modulePending')}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('uploadResources')}</CardTitle>
          <p className="text-xs text-muted-foreground mt-1">{t('uploadResourcesDesc')}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragOver(false);
              handleUpload(Array.from(e.dataTransfer.files));
            }}
            onClick={() => fileInputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors ${
              isDragOver
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/50 hover:bg-muted/50'
            }`}
            role="button"
            tabIndex={0}
            aria-label={t('addResource')}
            onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
          >
            <Upload className="mb-2 h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">{t('addResource')}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">PDF</p>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            onChange={(e) => {
              handleUpload(Array.from(e.target.files || []));
              e.target.value = '';
            }}
          />

          {uploadError && (
            <p className="text-xs text-destructive">{uploadError}</p>
          )}

          {uploadingFiles.length > 0 && (
            <div className="space-y-1">
              {uploadingFiles.map((name) => (
                <div key={name} className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span className="truncate">{name}</span>
                </div>
              ))}
            </div>
          )}

          {course.resources && course.resources.length > 0 ? (
            <div className="space-y-2">
              {course.resources.map((r) => (
                <div
                  key={r.name}
                  className="flex items-center gap-3 rounded-lg border bg-card p-3"
                >
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm font-medium">{r.name}</p>
                    <p className="text-xs text-muted-foreground">{formatBytes(r.size_bytes)}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => handleRemoveResource(r.name)}
                    aria-label={t('removeResource')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('noResources')}</p>
          )}

          {course.resources && course.resources.length > 0 && (
            <div className="space-y-3 pt-2 border-t">
              {!isIndexing && !indexStatus?.indexed && (
                <Button
                  onClick={startIndexation}
                  variant="outline"
                  className="w-full min-h-11 gap-2"
                  disabled={isIndexing}
                >
                  <Database className="h-4 w-4" />
                  {t('triggerIndexation')}
                </Button>
              )}

              {isIndexing && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">{t('indexing')}</p>
                  </div>
                  <Progress
                    value={indexStatus?.chunks_indexed ? 70 : 20}
                    className="h-2"
                  />
                </div>
              )}

              {indexError && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {indexError}
                </div>
              )}

              {indexStatus?.indexed && (
                <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <div>
                    <p className="text-sm font-medium text-green-700 dark:text-green-400">
                      {t('indexSuccess')}
                    </p>
                    <p className="text-xs text-green-600 dark:text-green-500">
                      {t('chunksIndexed', { count: indexStatus.chunks_indexed })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <AlertDialog open={showPublishDialog} onOpenChange={setShowPublishDialog}>
        <AlertDialogContent>
          <AlertDialogTitle>{t('confirmPublish')}</AlertDialogTitle>
          <AlertDialogDescription>{t('confirmPublishDesc')}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setShowPublishDialog(false)}>
              {t('cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => publishMutation.mutate()}
              disabled={publishMutation.isPending}
            >
              {publishMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Globe className="mr-2 h-4 w-4" />
              )}
              {t('publish')}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showUnpublishDialog} onOpenChange={setShowUnpublishDialog}>
        <AlertDialogContent>
          <AlertDialogTitle>{t('confirmUnpublish')}</AlertDialogTitle>
          <AlertDialogDescription>{t('confirmUnpublishDesc')}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setShowUnpublishDialog(false)}>
              {t('cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => unpublishMutation.mutate()}
              disabled={unpublishMutation.isPending}
            >
              {unpublishMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <GlobeLock className="mr-2 h-4 w-4" />
              )}
              {t('unpublish')}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
