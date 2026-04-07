"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  Trash2,
  Sparkles,
  Database,
  Rocket,
  CheckCircle2,
  X,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  AlertCircle,
  Clock,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
} from "@/components/ui/alert-dialog";
import { apiFetch, API_BASE, getCourseTaxonomy, type TaxonomyItem } from "@/lib/api";
import { authClient } from "@/lib/auth";

type WizardStep = "upload" | "info" | "generate" | "index" | "publish";

const STEPS: WizardStep[] = ["upload", "info", "generate", "index", "publish"];

function mapCreationStepToWizardStep(creationStep: string): WizardStep {
  switch (creationStep) {
    case "upload":
      return "upload";
    case "info":
      return "info";
    case "generating":
    case "generated":
      return "generate";
    case "indexing":
    case "indexed":
      return "index";
    case "published":
      return "publish";
    default:
      return "upload";
  }
}

interface UploadedFile {
  name: string;
  size_bytes: number;
  status: "uploading" | "uploaded" | "error";
  error?: string;
}

interface CourseInfo {
  title_fr: string;
  title_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  estimated_hours: number;
}

interface GeneratedModule {
  id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
}

interface TaskProgress {
  state: string;
  step?: string;
  step_label?: string;
  progress: number;
  files_total: number;
  files_processed: number;
  current_file?: string;
  chunks_processed: number;
  estimated_seconds_remaining?: number;
}

interface IndexStatus {
  indexed: boolean;
  chunks_indexed: number;
  images_indexed?: number;
  task?: TaskProgress;
}

interface CourseWizardClientProps {
  onClose: () => void;
  onCourseCreated: () => void;
  resumeCourseId?: string;
  resumeCreationStep?: string;
}

function AttachedResources({
  files,
  t,
}: {
  files: UploadedFile[];
  t: ReturnType<typeof useTranslations>;
}) {
  const [open, setOpen] = useState(true);
  const uploaded = files.filter((f) => f.status === "uploaded");
  if (uploaded.length === 0) return null;
  return (
    <div className="rounded-lg border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-sm font-medium min-h-[44px]"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span>{t("attachedResources.title")}</span>
          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary">
            {uploaded.length}
          </span>
        </div>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="border-t px-3 pb-3 pt-2 space-y-1.5">
          {uploaded.map((f) => (
            <div key={f.name} className="flex items-center gap-2.5">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{f.name}</p>
                <p className="text-xs text-muted-foreground">{formatBytes(f.size_bytes)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ETALabel({ seconds, t }: { seconds: number | undefined; t: ReturnType<typeof useTranslations> }) {
  if (seconds === undefined || seconds <= 0) return null;
  if (seconds < 60) return <span>{t("index.etaSeconds", { seconds })}</span>;
  return <span>{t("index.etaMinutes", { minutes: Math.ceil(seconds / 60) })}</span>;
}

export function CourseWizardClient({
  onClose,
  onCourseCreated,
  resumeCourseId,
  resumeCreationStep,
}: CourseWizardClientProps) {
  const t = useTranslations("AdminCourses.wizard");
  const locale = useLocale();
  const queryClient = useQueryClient();

  const initialStep = resumeCreationStep
    ? mapCreationStepToWizardStep(resumeCreationStep)
    : "upload";

  const [step, setStep] = useState<WizardStep>(initialStep);
  const [isDragOver, setIsDragOver] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [courseId, setCourseId] = useState<string | null>(resumeCourseId ?? null);
  const [courseInfo, setCourseInfo] = useState<CourseInfo>({
    title_fr: "",
    title_en: "",
    course_domain: [],
    course_level: [],
    audience_type: [],
    estimated_hours: 20,
  });
  const [infoErrors, setInfoErrors] = useState<Partial<CourseInfo>>({});
  const [domainOptions, setDomainOptions] = useState<TaxonomyItem[]>([]);
  const [levelOptions, setLevelOptions] = useState<TaxonomyItem[]>([]);
  const [audienceOptions, setAudienceOptions] = useState<TaxonomyItem[]>([]);
  const [isCreatingCourse, setIsCreatingCourse] = useState(false);
  const [generatedModules, setGeneratedModules] = useState<GeneratedModule[]>([]);
  const [isGenerating, setIsGenerating] = useState(
    resumeCreationStep === "generating"
  );
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateTaskId, setGenerateTaskId] = useState<string | null>(null);
  const [generateTaskState, setGenerateTaskState] = useState<string | null>(null);
  const [generationProgress, setGenerationProgress] = useState(0);
  const [generationStep, setGenerationStep] = useState<string | undefined>(undefined);
  const [generationStartTime, setGenerationStartTime] = useState<number | null>(null);
  const [generationElapsed, setGenerationElapsed] = useState(0);
  const [showTimeoutWarning, setShowTimeoutWarning] = useState(false);
  const lastProgressValueRef = useRef(0);
  const lastProgressTimeRef = useRef<number | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [isIndexing, setIsIndexing] = useState(
    resumeCreationStep === "indexing"
  );
  const [indexError, setIndexError] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishSummaryTitle, setPublishSummaryTitle] = useState<{ title_fr: string; title_en: string } | null>(null);
  const [publishSummaryIndexStatus, setPublishSummaryIndexStatus] = useState<IndexStatus | null>(null);
  const [publishSummaryResources, setPublishSummaryResources] = useState<Array<{ name: string }>>([]);
  const [publishSummaryModuleCount, setPublishSummaryModuleCount] = useState<number>(0);
  const [isFetchingPublishSummary, setIsFetchingPublishSummary] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generatePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stepIndex = STEPS.indexOf(step);

  useEffect(() => {
    getCourseTaxonomy().then((tax) => {
      setDomainOptions(tax.domains);
      setLevelOptions(tax.levels);
      setAudienceOptions(tax.audience_types);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!courseId || files.length > 0) return;
    apiFetch<{ files: Array<{ name: string; size_bytes: number }> }>(
      `/api/v1/admin/courses/${courseId}/resources`
    )
      .then((data) => {
        if (data.files?.length) {
          setFiles(
            data.files.map((f) => ({ name: f.name, size_bytes: f.size_bytes, status: "uploaded" as const }))
          );
        }
      })
      .catch(() => {});
  }, [courseId]); // eslint-disable-line react-hooks/exhaustive-deps

  const getAuthHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await authClient.getValidToken();
    return { Authorization: `Bearer ${token}` };
  }, []);

  const uploadFile = useCallback(
    async (file: File) => {
      if (!courseId) return;

      setFiles((prev) =>
        prev.map((f) =>
          f.name === file.name ? { ...f, status: "uploading" as const } : f
        )
      );

      const formData = new FormData();
      formData.append("file", file);

      const headers = await getAuthHeaders();
      const res = await fetch(`${API_BASE}/api/v1/admin/courses/${courseId}/resources`, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const msg = body?.detail || t("upload.uploadError");
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "error" as const, error: msg } : f
          )
        );
        return;
      }

      setFiles((prev) =>
        prev.map((f) => (f.name === file.name ? { ...f, status: "uploaded" as const } : f))
      );
    },
    [courseId, getAuthHeaders, t]
  );

  const handleFiles = useCallback(
    async (incoming: File[]) => {
      const pdfs = incoming.filter((f) => f.type === "application/pdf");
      if (!pdfs.length) return;

      const newEntries: UploadedFile[] = pdfs
        .filter((f) => !files.some((existing) => existing.name === f.name))
        .map((f) => ({ name: f.name, size_bytes: f.size, status: "uploading" as const }));

      if (!newEntries.length) return;
      setFiles((prev) => [...prev, ...newEntries]);

      if (courseId) {
        for (const file of pdfs) {
          await uploadFile(file);
        }
      } else {
        setFiles((prev) =>
          prev.map((f) =>
            newEntries.some((n) => n.name === f.name)
              ? { ...f, status: "uploaded" as const }
              : f
          )
        );
        setPendingFiles((prev) => [...prev, ...pdfs]);
      }
    },
    [courseId, files, uploadFile]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const incoming = Array.from(e.dataTransfer.files);
      handleFiles(incoming);
    },
    [handleFiles]
  );

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const incoming = Array.from(e.target.files || []);
      handleFiles(incoming);
      e.target.value = "";
    },
    [handleFiles]
  );

  const removeFile = useCallback(
    async (name: string) => {
      if (courseId) {
        const headers = await getAuthHeaders();
        await fetch(
          `${API_BASE}/api/v1/admin/courses/${courseId}/resources/${encodeURIComponent(name)}`,
          { method: "DELETE", headers }
        ).catch(() => {});
      }
      setFiles((prev) => prev.filter((f) => f.name !== name));
    },
    [courseId, getAuthHeaders]
  );

  const createCourseAndUploadFiles = useCallback(async () => {
    const errors: Partial<CourseInfo> = {};
    if (!courseInfo.title_fr.trim()) errors.title_fr = t("info.titleFrRequired");
    if (!courseInfo.title_en.trim()) errors.title_en = t("info.titleEnRequired");
    setInfoErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setIsCreatingCourse(true);

    try {
      const course = await apiFetch<{ id: string; creation_step: string }>("/api/v1/admin/courses", {
        method: "POST",
        body: JSON.stringify({
          title_fr: courseInfo.title_fr,
          title_en: courseInfo.title_en,
          course_domain: courseInfo.course_domain,
          course_level: courseInfo.course_level,
          audience_type: courseInfo.audience_type,
          estimated_hours: courseInfo.estimated_hours,
        }),
      });

      setCourseId(course.id);

      const headers = await getAuthHeaders();

      for (const file of pendingFiles) {
        const formData = new FormData();
        formData.append("file", file);
        await fetch(`${API_BASE}/api/v1/admin/courses/${course.id}/resources`, {
          method: "POST",
          headers,
          body: formData,
        });
      }

      if (pendingFiles.length > 0) {
        setFiles((prev) => prev.map((f) => ({ ...f, status: "uploaded" as const })));
        setPendingFiles([]);
      }

      setStep("generate");
    } catch {
      setInfoErrors({ title_fr: t("info.titleFrRequired") });
    } finally {
      setIsCreatingCourse(false);
    }
  }, [courseInfo, getAuthHeaders, t, pendingFiles]);

  const generateSyllabus = useCallback(async () => {
    if (!courseId) return;
    setIsGenerating(true);
    setGenerateError(null);
    setGenerateTaskId(null);
    setGenerateTaskState(null);
    setGenerationProgress(0);
    setGenerationStep(undefined);
    setGenerationStartTime(Date.now());
    setGenerationElapsed(0);
    lastProgressValueRef.current = 0;
    lastProgressTimeRef.current = Date.now();
    setShowTimeoutWarning(false);

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 300000);

      const result = await apiFetch<{ task_id: string; status: string }>(
        `/api/v1/admin/courses/${courseId}/generate-structure`,
        {
          method: "POST",
          body: JSON.stringify({
            estimated_hours: courseInfo.estimated_hours,
          }),
          signal: controller.signal,
        }
      );
      clearTimeout(timeout);
      setGenerateTaskId(result.task_id);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setGenerateError(t("generate.error") + " (timeout)");
      } else {
        setGenerateError(t("generate.error"));
      }
      setIsGenerating(false);
    }
  }, [courseId, courseInfo, t]);

  useEffect(() => {
    if (!courseId || !isGenerating || !generateTaskId) return;

    const poll = async () => {
      try {
        const status = await apiFetch<{
          has_modules: boolean;
          modules_count: number;
          task?: { state: string; meta?: Record<string, unknown> };
        }>(`/api/v1/admin/courses/${courseId}/generate-status?task_id=${generateTaskId}`);

        setGenerateTaskState(status.task?.state ?? null);

        const meta = status.task?.meta ?? {};
        const newProgress = typeof meta.progress === "number" ? meta.progress : 0;
        const newStep = typeof meta.step === "string" ? meta.step : undefined;

        setGenerationProgress(newProgress);
        setGenerationStep(newStep);

        if (newProgress !== lastProgressValueRef.current) {
          lastProgressValueRef.current = newProgress;
          lastProgressTimeRef.current = Date.now();
          setShowTimeoutWarning(false);
        } else if (lastProgressTimeRef.current !== null) {
          const staleSince = Date.now() - lastProgressTimeRef.current;
          if (staleSince > 2 * 60 * 1000) {
            setShowTimeoutWarning(true);
          }
        }

        if (
          status.task?.state === "FAILURE" ||
          status.task?.state === "REVOKED"
        ) {
          setGenerateError(t("generate.error"));
          setIsGenerating(false);
          return;
        }

        if (status.task?.state === "SUCCESS") {
          const modules = meta.modules;
          if (Array.isArray(modules)) {
            setGeneratedModules(modules as GeneratedModule[]);
          }
          setIsGenerating(false);
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
  }, [courseId, isGenerating, generateTaskId, t]);

  useEffect(() => {
    if (!isGenerating || generationStartTime === null) return;
    const interval = setInterval(() => {
      setGenerationElapsed(Math.floor((Date.now() - generationStartTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [isGenerating, generationStartTime]);

  const startIndexation = useCallback(async () => {
    if (!courseId) return;
    setIsIndexing(true);
    setIndexError(null);

    try {
      const result = await apiFetch<{ task_id: string; status: string }>(
        `/api/v1/admin/courses/${courseId}/index-resources`,
        { method: "POST" }
      );
      setTaskId(result.task_id);
    } catch {
      setIndexError(t("index.error"));
      setIsIndexing(false);
    }
  }, [courseId, t]);

  useEffect(() => {
    if (!courseId || !isIndexing) return;

    const poll = async () => {
      try {
        const params = taskId ? `?task_id=${taskId}` : "";
        const status = await apiFetch<{
          indexed: boolean;
          chunks_indexed: number;
          images_indexed?: number;
          task?: {
            state: string;
            step?: string;
            step_label?: string;
            progress: number;
            files_total: number;
            files_processed: number;
            current_file?: string;
            chunks_processed: number;
            estimated_seconds_remaining?: number;
          };
        }>(`/api/v1/admin/courses/${courseId}/index-status${params}`);

        setIndexStatus({
          indexed: status.indexed,
          chunks_indexed: status.chunks_indexed,
          images_indexed: status.images_indexed,
          task: status.task,
        });

        if (status.task?.state === "SUCCESS") {
          setIsIndexing(false);
          queryClient.invalidateQueries({ queryKey: ["admin-courses"] });
          return;
        }

        if (
          status.task?.state === "FAILURE" ||
          status.task?.state === "REVOKED"
        ) {
          setIndexError(t("index.error"));
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
  }, [courseId, isIndexing, taskId, t, queryClient]);

  useEffect(() => {
    if (step !== "publish" || !courseId) return;

    const fetchPublishSummary = async () => {
      setIsFetchingPublishSummary(true);
      try {
        const [courseData, statusData, resourcesData, modulesData] = await Promise.all([
          apiFetch<{ title_fr: string; title_en: string; module_count: number }>(`/api/v1/admin/courses/${courseId}`),
          apiFetch<{ indexed: boolean; chunks_indexed: number; images_indexed?: number }>(`/api/v1/admin/courses/${courseId}/index-status`),
          apiFetch<{ files: Array<{ name: string }> }>(`/api/v1/admin/courses/${courseId}/resources`),
          apiFetch<{ modules_count: number }>(`/api/v1/admin/courses/${courseId}/generate-status`),
        ]);
        setPublishSummaryTitle({ title_fr: courseData.title_fr, title_en: courseData.title_en });
        setPublishSummaryModuleCount(modulesData.modules_count ?? courseData.module_count ?? 0);
        setPublishSummaryIndexStatus(statusData);
        setPublishSummaryResources(resourcesData.files ?? []);
      } catch {
      } finally {
        setIsFetchingPublishSummary(false);
      }
    };

    fetchPublishSummary();
  }, [step, courseId]);

  const publishCourse = useCallback(async () => {
    if (!courseId) return;
    setIsPublishing(true);
    setPublishError(null);

    try {
      await apiFetch(`/api/v1/admin/courses/${courseId}/publish`, { method: "POST" });
      setPublishSuccess(true);
      queryClient.invalidateQueries({ queryKey: ["admin-courses"] });
      onCourseCreated();
    } catch {
      setPublishError(t("publish.error"));
    } finally {
      setIsPublishing(false);
    }
  }, [courseId, queryClient, onCourseCreated, t]);

  const handleClose = useCallback(() => {
    if (isIndexing) {
      setShowCloseConfirm(true);
      return;
    }
    onClose();
  }, [isIndexing, onClose]);

  const handleForceClose = useCallback(() => {
    setShowCloseConfirm(false);
    onClose();
  }, [onClose]);

  const canGoNext = (): boolean => {
    if (step === "upload") return files.filter((f) => f.status === "uploaded").length > 0;
    if (step === "info") return courseInfo.title_fr.trim().length > 0 && courseInfo.title_en.trim().length > 0;
    if (step === "generate") return generatedModules.length > 0;
    if (step === "index") return !!(indexStatus?.indexed && indexStatus.chunks_indexed > 0 && !isIndexing);
    return false;
  };

  const handleNext = () => {
    if (step === "upload" && !courseId) {
      setStep("info");
      return;
    }
    if (step === "info") {
      createCourseAndUploadFiles();
      return;
    }
    const idx = STEPS.indexOf(step);
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
  };

  const handleBack = () => {
    const idx = STEPS.indexOf(step);
    if (idx > 0) setStep(STEPS[idx - 1]);
  };

  const getGenerateStepLabel = (s: string | undefined): string => {
    switch (s) {
      case "extracting_text": return t("generate.stepExtractingText");
      case "calling_claude": return t("generate.stepCallingClaude");
      case "parsing_response": return t("generate.stepParsingResponse");
      case "saving_modules": return t("generate.stepSavingModules");
      default: return t("generate.taskRunning");
    }
  };

  const formatElapsed = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const getStepLabel = (s: string | undefined): string => {
    switch (s) {
      case "extracting": return t("index.stepExtracting");
      case "chunking": return t("index.stepChunking");
      case "embedding": return t("index.stepEmbedding");
      case "storing": return t("index.stepStoring");
      case "complete": return t("index.stepComplete");
      case "extracting_images": return t("index.stepExtractingImages");
      case "EXTRACTING_IMAGES": return t("index.stepExtractingImages");
      default: return t("index.taskPending");
    }
  };

  const StepIcon = ({ s }: { s: WizardStep }) => {
    const icons: Record<WizardStep, React.ReactNode> = {
      upload: <Upload className="h-4 w-4" />,
      info: <BookOpen className="h-4 w-4" />,
      generate: <Sparkles className="h-4 w-4" />,
      index: <Database className="h-4 w-4" />,
      publish: <Rocket className="h-4 w-4" />,
    };
    return <>{icons[s]}</>;
  };

  const taskProg = indexStatus?.task;
  const progressValue = taskProg?.progress ?? (indexStatus?.indexed ? 100 : 0);

  return (
    <>
      <div className="fixed inset-0 z-50 flex flex-col bg-background">
        <div className="flex items-center justify-between border-b px-4 py-3 shrink-0">
          <h2 className="text-lg font-semibold">{t("title")}</h2>
          <Button variant="ghost" size="icon" onClick={handleClose} aria-label={t("close")}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="border-b px-4 py-3 shrink-0">
          <div className="flex items-center gap-1 overflow-x-auto">
            {STEPS.map((s, i) => (
              <div key={s} className="flex items-center gap-1 shrink-0">
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                    s === step
                      ? "bg-primary text-primary-foreground"
                      : i < stepIndex
                      ? "bg-primary/20 text-primary"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {i < stepIndex ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <StepIcon s={s} />
                  )}
                  <span className="hidden sm:inline">{t(`steps.${s}`)}</span>
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`h-px w-4 ${i < stepIndex ? "bg-primary/40" : "bg-border"}`} />
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto max-w-2xl">
            {step === "upload" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("upload.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("upload.description")}</p>
                </div>

                <div
                  onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={onDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
                    isDragOver
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50 hover:bg-muted/50"
                  }`}
                  role="button"
                  tabIndex={0}
                  aria-label={t("upload.dropzone")}
                  onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
                >
                  <Upload className="mb-3 h-8 w-8 text-muted-foreground" />
                  <p className="text-sm font-medium">
                    {isDragOver ? t("upload.dropzoneActive") : t("upload.dropzone")}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{t("upload.fileTypes")}</p>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf"
                  multiple
                  className="hidden"
                  onChange={onFileInput}
                />

                {files.length > 0 && (
                  <div className="space-y-2">
                    {files.map((f) => (
                      <div
                        key={f.name}
                        className="flex items-center gap-3 rounded-lg border bg-card p-3"
                      >
                        <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{f.name}</p>
                          <p className="text-xs text-muted-foreground">{formatBytes(f.size_bytes)}</p>
                        </div>
                        {f.status === "uploading" && (
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        )}
                        {f.status === "uploaded" && (
                          <CheckCircle2 className="h-4 w-4 text-green-600" />
                        )}
                        {f.status === "error" && (
                          <span title={f.error}><AlertCircle className="h-4 w-4 text-destructive" /></span>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0"
                          onClick={(e) => { e.stopPropagation(); removeFile(f.name); }}
                          aria-label={t("upload.remove")}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {step === "info" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("info.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("info.description")}</p>
                </div>

                <AttachedResources files={files} t={t} />

                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="title_fr">{t("info.titleFr")} *</Label>
                    <Input
                      id="title_fr"
                      value={courseInfo.title_fr}
                      onChange={(e) => setCourseInfo((p) => ({ ...p, title_fr: e.target.value }))}
                      placeholder="Santé Publique en Afrique de l'Ouest"
                      className={infoErrors.title_fr ? "border-destructive" : ""}
                    />
                    {infoErrors.title_fr && (
                      <p className="text-xs text-destructive">{infoErrors.title_fr}</p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="title_en">{t("info.titleEn")} *</Label>
                    <Input
                      id="title_en"
                      value={courseInfo.title_en}
                      onChange={(e) => setCourseInfo((p) => ({ ...p, title_en: e.target.value }))}
                      placeholder="Public Health in West Africa"
                      className={infoErrors.title_en ? "border-destructive" : ""}
                    />
                    {infoErrors.title_en && (
                      <p className="text-xs text-destructive">{infoErrors.title_en}</p>
                    )}
                  </div>

                  {[
                    { label: t("info.domain"), options: domainOptions, field: "course_domain" as const },
                    { label: t("info.level"), options: levelOptions, field: "course_level" as const },
                    { label: t("info.audience"), options: audienceOptions, field: "audience_type" as const },
                  ].map(({ label, options, field }) => (
                    <div key={field} className="space-y-1.5">
                      <Label>{label}</Label>
                      <div className="flex flex-wrap gap-1.5">
                        {options.map((opt) => {
                          const sel = courseInfo[field].includes(opt.value);
                          return (
                            <button
                              key={opt.value}
                              type="button"
                              onClick={() =>
                                setCourseInfo((p) => ({
                                  ...p,
                                  [field]: sel
                                    ? p[field].filter((v: string) => v !== opt.value)
                                    : [...p[field], opt.value],
                                }))
                              }
                              className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors min-h-[32px] ${
                                sel
                                  ? "bg-teal-600 text-white hover:bg-teal-700"
                                  : "bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200"
                              }`}
                            >
                              {locale === "fr" ? opt.label_fr : opt.label_en}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}

                  <div className="space-y-1.5">
                    <Label htmlFor="estimated_hours">{t("info.estimatedHours")}</Label>
                    <Input
                      id="estimated_hours"
                      type="number"
                      min={1}
                      max={500}
                      value={courseInfo.estimated_hours}
                      onChange={(e) =>
                        setCourseInfo((p) => ({
                          ...p,
                          estimated_hours: parseInt(e.target.value) || 20,
                        }))
                      }
                    />
                  </div>
                </div>
              </div>
            )}

            {step === "generate" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("generate.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("generate.description")}</p>
                </div>

                <AttachedResources files={files} t={t} />

                {generatedModules.length === 0 && !isGenerating && (
                  <Button
                    onClick={generateSyllabus}
                    className="w-full min-h-11"
                    disabled={isGenerating}
                  >
                    <Sparkles className="mr-2 h-4 w-4" />
                    {t("generate.button")}
                  </Button>
                )}

                {isGenerating && (
                  <div className="flex flex-col gap-3 rounded-lg border bg-card p-4">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent shrink-0" />
                        <p className="text-sm font-medium">
                          {generationStep
                            ? getGenerateStepLabel(generationStep)
                            : generateTaskState
                            ? t("generate.taskRunning")
                            : t("generate.taskPending")}
                        </p>
                      </div>
                      {generationStartTime !== null && (
                        <div className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
                          <Clock className="h-3 w-3" />
                          <span>{t("generate.elapsed", { time: formatElapsed(generationElapsed) })}</span>
                        </div>
                      )}
                    </div>
                    <Progress value={generationProgress} className="h-2" />
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>{generationProgress}%</span>
                    </div>
                    {showTimeoutWarning && (
                      <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        {t("generate.timeoutWarning")}
                      </div>
                    )}
                  </div>
                )}

                {generateError && (
                  <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {generateError}
                  </div>
                )}

                {generatedModules.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                      <p className="text-sm font-medium text-green-700">
                        {t("generate.moduleCount", { count: generatedModules.length })}
                      </p>
                    </div>
                    <div className="space-y-2 max-h-80 overflow-y-auto">
                      {generatedModules.map((m) => (
                        <div
                          key={m.id}
                          className="flex items-center gap-3 rounded-lg border bg-card p-3"
                        >
                          <Badge variant="outline" className="shrink-0 text-xs">
                            M{m.module_number}
                          </Badge>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">{m.title_fr}</p>
                            <p className="truncate text-xs text-muted-foreground">{m.title_en}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {step === "index" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("index.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("index.description")}</p>
                </div>

                <AttachedResources files={files} t={t} />

                {!isIndexing && !indexStatus?.indexed && (
                  <Button onClick={startIndexation} className="w-full min-h-11" disabled={isIndexing}>
                    <Database className="mr-2 h-4 w-4" />
                    {t("index.button")}
                  </Button>
                )}

                {isIndexing && (
                  <div className="space-y-4">
                    <div className="rounded-lg border bg-card p-4 space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent shrink-0" />
                          <p className="text-sm font-medium">
                            {taskProg
                              ? (taskProg.state === "EXTRACTING_IMAGES"
                                ? t("index.stepExtractingImages")
                                : getStepLabel(taskProg.step))
                              : t("index.taskPending")}
                          </p>
                        </div>
                        {taskProg?.estimated_seconds_remaining !== undefined && taskProg.estimated_seconds_remaining > 0 && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
                            <Clock className="h-3 w-3" />
                            <ETALabel seconds={taskProg.estimated_seconds_remaining} t={t} />
                          </div>
                        )}
                      </div>

                      <Progress value={progressValue} className="h-2" />

                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>{progressValue}%</span>
                        {taskProg && taskProg.files_total > 0 && (
                          <span>
                            {t("index.filesProgress", {
                              current: taskProg.files_processed,
                              total: taskProg.files_total,
                            })}
                          </span>
                        )}
                      </div>

                      {taskProg?.current_file && (
                        <p className="text-xs text-muted-foreground truncate">
                          {taskProg.current_file}
                        </p>
                      )}

                      {taskProg && taskProg.chunks_processed > 0 && (
                        <p className="text-xs text-muted-foreground">
                          {t("index.chunksProgress", { count: taskProg.chunks_processed })}
                        </p>
                      )}

                      {taskProg?.state === "EXTRACTING_IMAGES" && indexStatus?.images_indexed !== undefined && indexStatus.images_indexed > 0 && (
                        <p className="text-xs text-muted-foreground">
                          {t("index.imagesProgress", { count: indexStatus.images_indexed })}
                        </p>
                      )}
                    </div>

                    <p className="text-xs text-muted-foreground text-center">
                      {t("index.resumeHint")}
                    </p>
                  </div>
                )}

                {indexError && (
                  <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {indexError}
                  </div>
                )}

                {indexStatus?.indexed && !isIndexing && (
                  <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    <div>
                      <p className="text-sm font-medium text-green-700 dark:text-green-400">
                        {t("index.indexed")}
                      </p>
                      <p className="text-xs text-green-600 dark:text-green-500">
                        {indexStatus.images_indexed && indexStatus.images_indexed > 0
                          ? t("index.chunksAndImagesIndexed", {
                              chunks: indexStatus.chunks_indexed,
                              images: indexStatus.images_indexed,
                            })
                          : t("index.chunksIndexed", { count: indexStatus.chunks_indexed })}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}

            {step === "publish" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("publish.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("publish.description")}</p>
                </div>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{t("publish.summary.title")}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {isFetchingPublishSummary ? (
                      <div className="flex items-center justify-center py-4">
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                      </div>
                    ) : (
                      <>
                        {publishSummaryTitle && (
                          <>
                            <div className="flex justify-between gap-4">
                              <span className="text-muted-foreground shrink-0">{t("publish.summary.titleFr")}</span>
                              <span className="font-medium text-right truncate">{publishSummaryTitle.title_fr}</span>
                            </div>
                            <div className="flex justify-between gap-4">
                              <span className="text-muted-foreground shrink-0">{t("publish.summary.titleEn")}</span>
                              <span className="font-medium text-right truncate">{publishSummaryTitle.title_en}</span>
                            </div>
                          </>
                        )}
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">{t("publish.summary.modules")}</span>
                          <span className="font-medium">{publishSummaryModuleCount}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">{t("publish.summary.chunks")}</span>
                          <span className="font-medium">{publishSummaryIndexStatus?.chunks_indexed ?? 0}</span>
                        </div>
                        {(publishSummaryIndexStatus?.images_indexed ?? 0) > 0 && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">{t("publish.summary.images")}</span>
                            <span className="font-medium">{publishSummaryIndexStatus?.images_indexed}</span>
                          </div>
                        )}
                        {publishSummaryResources.length > 0 && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground shrink-0">{t("publish.summary.resources")}</span>
                            <span className="font-medium text-right">
                              {t("publish.summary.resourcesCount", { count: publishSummaryResources.length })}
                            </span>
                          </div>
                        )}
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">{t("publish.summary.status")}</span>
                          <Badge variant="outline" className="text-amber-600 border-amber-300">
                            draft
                          </Badge>
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>

                {publishSuccess ? (
                  <div className="flex flex-col items-center gap-3 py-4 text-center">
                    <CheckCircle2 className="h-12 w-12 text-green-600" />
                    <div>
                      <p className="font-semibold text-green-700">{t("publish.success")}</p>
                      <p className="text-sm text-muted-foreground">{t("publish.successDesc")}</p>
                    </div>
                    <Button onClick={onClose} className="mt-2">
                      {t("close")}
                    </Button>
                  </div>
                ) : (
                  <>
                    {publishError && (
                      <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                        <AlertCircle className="h-4 w-4 shrink-0" />
                        {publishError}
                      </div>
                    )}
                    <Button
                      onClick={publishCourse}
                      className="w-full min-h-11"
                      disabled={isPublishing}
                    >
                      {isPublishing ? (
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" />
                      ) : (
                        <Rocket className="mr-2 h-4 w-4" />
                      )}
                      {isPublishing ? t("publish.publishing") : t("publish.button")}
                    </Button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {!publishSuccess && (
          <div className="flex items-center justify-between border-t bg-background px-4 py-3 shrink-0">
            <Button
              variant="outline"
              onClick={handleBack}
              disabled={stepIndex === 0}
              className="min-h-11"
            >
              <ChevronLeft className="mr-1 h-4 w-4" />
              {t("back")}
            </Button>

            {step !== "publish" && (
              <Button
                onClick={handleNext}
                disabled={!canGoNext() || isCreatingCourse || isGenerating}
                className="min-h-11"
              >
                {isCreatingCourse ? (
                  <>
                    <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    {t("info.creating")}
                  </>
                ) : (
                  <>
                    {t("next")}
                    <ChevronRight className="ml-1 h-4 w-4" />
                  </>
                )}
              </Button>
            )}
          </div>
        )}
      </div>

      <AlertDialog open={showCloseConfirm} onOpenChange={setShowCloseConfirm}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("closeWhileRunning.title")}</AlertDialogTitle>
          <AlertDialogDescription>{t("closeWhileRunning.description")}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <Button variant="outline" onClick={() => setShowCloseConfirm(false)}>
              {t("closeWhileRunning.cancel")}
            </Button>
            <Button onClick={handleForceClose}>
              {t("closeWhileRunning.confirmClose")}
            </Button>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
