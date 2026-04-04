'use client';

import { useCallback, useRef, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
  CheckCircle,
  ChevronRight,
  ChevronLeft,
  FileText,
  Loader2,
  Sparkles,
  Upload,
  X,
  BookOpen,
  Database,
  Globe,
} from 'lucide-react';
import { authClient, AuthError } from '@/lib/auth';
import { useRouter } from 'next/navigation';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CourseResponse {
  id: string;
  title_fr: string;
  title_en: string;
  status: string;
  module_count: number;
  estimated_hours: number;
  rag_collection_id: string | null;
}

interface CourseResource {
  id: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  chunks_indexed: number;
}

interface GeneratedModule {
  id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
}

interface CourseWizardClientProps {
  onClose: () => void;
  onCreated: () => void;
}

const STEPS = ['step1', 'step2', 'step3', 'step4', 'step5'] as const;
type Step = (typeof STEPS)[number];

function StepIndicator({ current, step, index }: { current: Step; step: Step; index: number }) {
  const stepIndex = STEPS.indexOf(step);
  const currentIndex = STEPS.indexOf(current);
  const done = stepIndex < currentIndex;
  const active = step === current;

  return (
    <div
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
        done
          ? 'bg-primary text-primary-foreground'
          : active
            ? 'border-2 border-primary text-primary'
            : 'border-2 border-muted-foreground/30 text-muted-foreground'
      }`}
    >
      {done ? <CheckCircle className="h-4 w-4" /> : index + 1}
    </div>
  );
}

export function CourseWizardClient({ onClose, onCreated }: CourseWizardClientProps) {
  const t = useTranslations('AdminCourses');
  const locale = useLocale() as 'fr' | 'en';
  const router = useRouter();

  const [currentStep, setCurrentStep] = useState<Step>('step1');
  const [course, setCourse] = useState<CourseResponse | null>(null);
  const [resources, setResources] = useState<CourseResource[]>([]);
  const [generatedModules, setGeneratedModules] = useState<GeneratedModule[]>([]);
  const [syllabusApproved, setSyllabusApproved] = useState(false);
  const [indexResult, setIndexResult] = useState<{ indexed: number; total_chunks: number } | null>(
    null
  );

  const [titleFr, setTitleFr] = useState('');
  const [titleEn, setTitleEn] = useState('');
  const [domain, setDomain] = useState('');
  const [audience, setAudience] = useState('');
  const [hours, setHours] = useState('20');

  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexError, setIndexError] = useState('');
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [published, setPublished] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

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

  const uploadFilesToCourse = useCallback(async (courseId: string, files: FileList) => {
    setUploadingFiles(true);
    setUploadErrors([]);
    const errors: string[] = [];

    for (const file of Array.from(files)) {
      if (file.type !== 'application/pdf') {
        errors.push(t('step1.uploadError', { name: file.name }));
        continue;
      }
      try {
        const token = await getToken();
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}/resources`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const resource: CourseResource = await res.json();
        setResources((prev) => [...prev, resource]);
      } catch {
        errors.push(t('step1.uploadError', { name: file.name }));
      }
    }

    if (errors.length > 0) setUploadErrors(errors);
    setUploadingFiles(false);
  }, [getToken, t]);

  const handleFileDrop = useCallback(
    async (files: FileList) => {
      if (!course) {
        if (!titleFr.trim() || !titleEn.trim()) {
          setCreateError(t('step2.required'));
          return;
        }
        setIsCreating(true);
        setCreateError('');
        try {
          const token = await getToken();
          const res = await fetch(`${API_BASE}/api/v1/admin/courses`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({
              title_fr: titleFr,
              title_en: titleEn,
              domain: domain || undefined,
              target_audience: audience || undefined,
              estimated_hours: parseInt(hours) || 20,
            }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const created: CourseResponse = await res.json();
          setCourse(created);
          await uploadFilesToCourse(created.id, files);
        } catch {
          setCreateError(t('createForm.createError'));
        } finally {
          setIsCreating(false);
        }
      } else {
        await uploadFilesToCourse(course.id, files);
      }
    },
    [course, titleFr, titleEn, domain, audience, hours, t, getToken, uploadFilesToCourse]
  );

  const removeResource = async (resourceId: string) => {
    setResources((prev) => prev.filter((r) => r.id !== resourceId));
  };

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (e.dataTransfer.files.length > 0) {
        handleFileDrop(e.dataTransfer.files);
      }
    },
    [handleFileDrop]
  );

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFileDrop(e.target.files);
        e.target.value = '';
      }
    },
    [handleFileDrop]
  );

  const createCourseAndContinue = async () => {
    if (!titleFr.trim() || !titleEn.trim()) {
      setCreateError(t('step2.required'));
      return;
    }

    let courseId = course?.id;

    if (!course) {
      setIsCreating(true);
      setCreateError('');
      try {
        const token = await getToken();
        const res = await fetch(`${API_BASE}/api/v1/admin/courses`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            title_fr: titleFr,
            title_en: titleEn,
            domain: domain || undefined,
            target_audience: audience || undefined,
            estimated_hours: parseInt(hours) || 20,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const created: CourseResponse = await res.json();
        setCourse(created);
        courseId = created.id;
      } catch {
        setCreateError(t('createForm.createError'));
        setIsCreating(false);
        return;
      }
      setIsCreating(false);
    }

    setIsGenerating(true);
    setGenerateError('');
    try {
      const token = await getToken();
      const res = await fetch(
        `${API_BASE}/api/v1/admin/courses/${courseId}/generate-structure`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            estimated_hours: parseInt(hours) || 20,
            target_audience: audience || undefined,
          }),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { modules: GeneratedModule[]; count: number } = await res.json();
      setGeneratedModules(data.modules);
      setCurrentStep('step3');
    } catch {
      setGenerateError(t('step2.generateError'));
    } finally {
      setIsGenerating(false);
    }
  };

  const handleIndex = async () => {
    if (!course) return;
    setIsIndexing(true);
    setIndexError('');
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${course.id}/index-resources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { indexed: number; total_chunks: number } = await res.json();
      setIndexResult(data);
      setCurrentStep('step5');
    } catch {
      setIndexError(t('step4.indexError'));
    } finally {
      setIsIndexing(false);
    }
  };

  const handlePublish = async () => {
    if (!course) return;
    setIsPublishing(true);
    setPublishError('');
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${course.id}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPublished(true);
      onCreated();
    } catch {
      setPublishError(t('step5.publishError'));
    } finally {
      setIsPublishing(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const stepProgress = (STEPS.indexOf(currentStep) / (STEPS.length - 1)) * 100;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-base font-semibold">{t('wizard.title')}</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label={t('wizard.close')}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="border-b px-4 py-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          {STEPS.map((step, i) => (
            <div key={step} className="flex flex-1 items-center gap-1">
              <div className="flex flex-col items-center gap-1">
                <StepIndicator current={currentStep} step={step} index={i} />
                <span className="hidden text-xs text-muted-foreground sm:block">
                  {t(`wizard.${step}`)}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className="mb-4 h-px flex-1 bg-border" />
              )}
            </div>
          ))}
        </div>
        <Progress value={stepProgress} className="h-1" />
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        {currentStep === 'step1' && (
          <Step1
            t={t}
            resources={resources}
            uploadingFiles={uploadingFiles}
            uploadErrors={uploadErrors}
            isCreating={isCreating}
            dropZoneRef={dropZoneRef}
            fileInputRef={fileInputRef}
            onDrop={handleDrop}
            onFileInputChange={handleFileInputChange}
            onRemove={removeResource}
            formatBytes={formatBytes}
          />
        )}

        {currentStep === 'step2' && (
          <Step2
            t={t}
            titleFr={titleFr}
            titleEn={titleEn}
            domain={domain}
            audience={audience}
            hours={hours}
            isGenerating={isGenerating}
            isCreating={isCreating}
            generateError={generateError}
            createError={createError}
            generatedModules={generatedModules}
            locale={locale}
            setTitleFr={setTitleFr}
            setTitleEn={setTitleEn}
            setDomain={setDomain}
            setAudience={setAudience}
            setHours={setHours}
          />
        )}

        {currentStep === 'step3' && (
          <Step3
            t={t}
            generatedModules={generatedModules}
            locale={locale}
            syllabusApproved={syllabusApproved}
            setSyllabusApproved={setSyllabusApproved}
          />
        )}

        {currentStep === 'step4' && (
          <Step4
            t={t}
            resources={resources}
            isIndexing={isIndexing}
            indexError={indexError}
            indexResult={indexResult}
            onIndex={handleIndex}
          />
        )}

        {currentStep === 'step5' && (
          <Step5
            t={t}
            course={course}
            locale={locale}
            indexResult={indexResult}
            isPublishing={isPublishing}
            publishError={publishError}
            published={published}
            onPublish={handlePublish}
          />
        )}
      </div>

      <div className="flex justify-between border-t px-4 py-3">
        <Button
          variant="outline"
          onClick={() => {
            const idx = STEPS.indexOf(currentStep);
            if (idx > 0) setCurrentStep(STEPS[idx - 1]);
          }}
          disabled={currentStep === 'step1'}
          className="min-h-11"
        >
          <ChevronLeft className="mr-1 h-4 w-4" />
          {t('wizard.back')}
        </Button>

        {currentStep === 'step1' && (
          <Button
            onClick={() => setCurrentStep('step2')}
            disabled={uploadingFiles}
            className="min-h-11"
          >
            {t('wizard.next')}
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        )}

        {currentStep === 'step2' && (
          <Button
            onClick={createCourseAndContinue}
            disabled={isGenerating || isCreating || !titleFr.trim() || !titleEn.trim()}
            className="min-h-11"
          >
            {isGenerating || isCreating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            {t('step2.generate')}
          </Button>
        )}

        {currentStep === 'step3' && (
          <Button
            onClick={() => {
              setSyllabusApproved(true);
              setCurrentStep('step4');
            }}
            disabled={generatedModules.length === 0}
            className="min-h-11"
          >
            {t('step3.approve')}
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        )}

        {currentStep === 'step4' && indexResult && (
          <Button onClick={() => setCurrentStep('step5')} className="min-h-11">
            {t('wizard.next')}
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        )}

        {currentStep === 'step5' && !published && (
          <Button
            onClick={handlePublish}
            disabled={isPublishing}
            className="min-h-11 bg-green-600 hover:bg-green-700"
          >
            {isPublishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Globe className="mr-2 h-4 w-4" />
            )}
            {t('step5.publish')}
          </Button>
        )}

        {currentStep === 'step5' && published && (
          <Button onClick={onClose} className="min-h-11">
            {t('wizard.close')}
          </Button>
        )}
      </div>
    </div>
  );
}

interface Step1Props {
  t: ReturnType<typeof useTranslations<'AdminCourses'>>;
  resources: CourseResource[];
  uploadingFiles: boolean;
  uploadErrors: string[];
  isCreating: boolean;
  dropZoneRef: React.RefObject<HTMLDivElement | null>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onDrop: (e: React.DragEvent<HTMLDivElement>) => void;
  onFileInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onRemove: (id: string) => void;
  formatBytes: (bytes: number) => string;
}

function Step1({
  t,
  resources,
  uploadingFiles,
  uploadErrors,
  isCreating,
  dropZoneRef,
  fileInputRef,
  onDrop,
  onFileInputChange,
  onRemove,
  formatBytes,
}: Step1Props) {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{t('step1.title')}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('step1.subtitle')}</p>
      </div>

      <div
        ref={dropZoneRef}
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border p-8 text-center transition-colors hover:border-primary/50"
      >
        <Upload className="h-8 w-8 text-muted-foreground" />
        <div className="text-sm text-muted-foreground">
          {t('step1.dropzone')}{' '}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="text-primary underline underline-offset-2 hover:text-primary/80"
          >
            {t('step1.browse')}
          </button>
        </div>
        <span className="text-xs text-muted-foreground">{t('step1.maxSize')}</span>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="sr-only"
          onChange={onFileInputChange}
          aria-label={t('step1.browse')}
        />
      </div>

      {(uploadingFiles || isCreating) && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('step1.uploading')}
        </div>
      )}

      {uploadErrors.length > 0 && (
        <div className="space-y-1">
          {uploadErrors.map((err, i) => (
            <p key={i} className="text-sm text-destructive">
              {err}
            </p>
          ))}
        </div>
      )}

      {resources.length === 0 && !uploadingFiles && (
        <p className="text-center text-sm text-muted-foreground">{t('step1.noFiles')}</p>
      )}

      {resources.length > 0 && (
        <ul className="space-y-2">
          {resources.map((r) => (
            <li key={r.id} className="flex items-center gap-3 rounded-md border px-3 py-2">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{r.original_name}</p>
                <p className="text-xs text-muted-foreground">{formatBytes(r.size_bytes)}</p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => onRemove(r.id)}
                aria-label={t('step1.removeFile')}
              >
                <X className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Step2Props {
  t: ReturnType<typeof useTranslations<'AdminCourses'>>;
  titleFr: string;
  titleEn: string;
  domain: string;
  audience: string;
  hours: string;
  isGenerating: boolean;
  isCreating: boolean;
  generateError: string;
  createError: string;
  generatedModules: GeneratedModule[];
  locale: 'fr' | 'en';
  setTitleFr: (v: string) => void;
  setTitleEn: (v: string) => void;
  setDomain: (v: string) => void;
  setAudience: (v: string) => void;
  setHours: (v: string) => void;
}

function Step2({
  t,
  titleFr,
  titleEn,
  domain,
  audience,
  hours,
  isGenerating,
  isCreating,
  generateError,
  createError,
  generatedModules,
  setTitleFr,
  setTitleEn,
  setDomain,
  setAudience,
  setHours,
}: Step2Props) {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{t('step2.title')}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('step2.subtitle')}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="titleFr">{t('step2.titleFrLabel')}</Label>
          <Input
            id="titleFr"
            value={titleFr}
            onChange={(e) => setTitleFr(e.target.value)}
            className="h-11"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="titleEn">{t('step2.titleEnLabel')}</Label>
          <Input
            id="titleEn"
            value={titleEn}
            onChange={(e) => setTitleEn(e.target.value)}
            className="h-11"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="domain">{t('step2.domainLabel')}</Label>
          <Input
            id="domain"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="h-11"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="hours">{t('step2.hoursLabel')}</Label>
          <Input
            id="hours"
            type="number"
            min={1}
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            className="h-11"
          />
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="audience">{t('step2.audienceLabel')}</Label>
        <Input
          id="audience"
          value={audience}
          onChange={(e) => setAudience(e.target.value)}
          className="h-11"
        />
      </div>

      {(generateError || createError) && (
        <p className="text-sm text-destructive">{generateError || createError}</p>
      )}

      {(isGenerating || isCreating) && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('step2.generating')}
        </div>
      )}

      {generatedModules.length > 0 && (
        <div className="rounded-md bg-primary/5 px-3 py-2 text-sm text-primary">
          <CheckCircle className="mr-1 inline h-4 w-4" />
          {t('step2.generatedModules', { count: generatedModules.length })}
        </div>
      )}
    </div>
  );
}

interface Step3Props {
  t: ReturnType<typeof useTranslations<'AdminCourses'>>;
  generatedModules: GeneratedModule[];
  locale: 'fr' | 'en';
  syllabusApproved: boolean;
  setSyllabusApproved: (v: boolean) => void;
}

function Step3({ t, generatedModules, locale, syllabusApproved }: Step3Props) {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{t('step3.title')}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('step3.subtitle')}</p>
      </div>

      <div className="space-y-2">
        {generatedModules.map((mod) => (
          <div key={mod.id} className="flex items-center gap-3 rounded-md border px-3 py-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              M{String(mod.module_number).padStart(2, '0')}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {locale === 'fr' ? mod.title_fr : mod.title_en}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {locale === 'fr' ? mod.title_en : mod.title_fr}
              </p>
            </div>
            <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
          </div>
        ))}
      </div>

      {syllabusApproved && (
        <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">
          <CheckCircle className="h-4 w-4" />
          {t('step3.approved')}
        </div>
      )}
    </div>
  );
}

interface Step4Props {
  t: ReturnType<typeof useTranslations<'AdminCourses'>>;
  resources: CourseResource[];
  isIndexing: boolean;
  indexError: string;
  indexResult: { indexed: number; total_chunks: number } | null;
  onIndex: () => void;
}

function Step4({ t, resources, isIndexing, indexError, indexResult, onIndex }: Step4Props) {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{t('step4.title')}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('step4.subtitle')}</p>
      </div>

      {resources.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('step4.noResources')}</p>
      )}

      {resources.length > 0 && !indexResult && (
        <div className="space-y-3">
          <ul className="space-y-2">
            {resources.map((r) => (
              <li key={r.id} className="flex items-center gap-3 rounded-md border px-3 py-2">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate text-sm">{r.original_name}</span>
              </li>
            ))}
          </ul>

          <Button
            onClick={onIndex}
            disabled={isIndexing}
            className="w-full min-h-11"
          >
            {isIndexing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Database className="mr-2 h-4 w-4" />
            )}
            {isIndexing ? t('step4.indexing') : t('step4.startIndex')}
          </Button>
        </div>
      )}

      {indexError && <p className="text-sm text-destructive">{indexError}</p>}

      {indexResult && (
        <div className="space-y-3 rounded-md bg-green-50 px-4 py-3">
          <div className="flex items-center gap-2 text-green-700">
            <CheckCircle className="h-5 w-5" />
            <span className="font-medium">{t('step4.done')}</span>
          </div>
          <Separator className="bg-green-200" />
          <p className="text-sm text-green-700">
            {t('step4.chunksIndexed', { count: indexResult.total_chunks })}
          </p>
        </div>
      )}
    </div>
  );
}

interface Step5Props {
  t: ReturnType<typeof useTranslations<'AdminCourses'>>;
  course: CourseResponse | null;
  locale: 'fr' | 'en';
  indexResult: { indexed: number; total_chunks: number } | null;
  isPublishing: boolean;
  publishError: string;
  published: boolean;
  onPublish: () => void;
}

function Step5({
  t,
  course,
  locale,
  indexResult,
  publishError,
  published,
}: Step5Props) {
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{t('step5.title')}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('step5.subtitle')}</p>
      </div>

      {course && (
        <div className="rounded-md border px-4 py-4 space-y-3">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              {locale === 'fr' ? 'Titre' : 'Title'}
            </p>
            <p className="mt-0.5 font-medium">
              {locale === 'fr' ? course.title_fr : course.title_en}
            </p>
          </div>
          <Separator />
          <div className="flex gap-6 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">{t('modules', { count: course.module_count })}</p>
            </div>
            {indexResult && (
              <div>
                <p className="text-xs text-muted-foreground">
                  {t('step4.chunksIndexed', { count: indexResult.total_chunks })}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {publishError && <p className="text-sm text-destructive">{publishError}</p>}

      {published && (
        <div className="flex items-center gap-2 rounded-md bg-green-50 px-4 py-3 text-green-700">
          <CheckCircle className="h-5 w-5" />
          <span className="font-medium">{t('step5.published')}</span>
        </div>
      )}
    </div>
  );
}
