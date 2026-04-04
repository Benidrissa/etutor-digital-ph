"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch, API_BASE } from "@/lib/api";
import { authClient } from "@/lib/auth";

type WizardStep = "upload" | "info" | "generate" | "index" | "publish";

const STEPS: WizardStep[] = ["upload", "info", "generate", "index", "publish"];

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

interface CourseWizardClientProps {
  onClose: () => void;
  onCourseCreated: () => void;
}

const DOMAIN_OPTIONS = [
  "health_sciences", "natural_sciences", "social_sciences",
  "mathematics", "engineering", "information_technology",
  "education", "arts_humanities", "business_management",
  "law", "agriculture", "environmental_studies", "other",
] as const;

const LEVEL_OPTIONS = [
  "beginner", "intermediate", "advanced", "expert",
] as const;

const AUDIENCE_OPTIONS = [
  "kindergarten", "primary_school", "secondary_school",
  "university", "professional", "researcher",
  "teacher", "policy_maker", "continuing_education",
] as const;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CourseWizardClient({ onClose, onCourseCreated }: CourseWizardClientProps) {
  const t = useTranslations("AdminCourses.wizard");
  const tTax = useTranslations("Taxonomy");
  const queryClient = useQueryClient();

  const [step, setStep] = useState<WizardStep>("upload");
  const [isDragOver, setIsDragOver] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [courseInfo, setCourseInfo] = useState<CourseInfo>({
    title_fr: "",
    title_en: "",
    course_domain: [],
    course_level: [],
    audience_type: [],
    estimated_hours: 20,
  });
  const [infoErrors, setInfoErrors] = useState<Partial<CourseInfo>>({});
  const [isCreatingCourse, setIsCreatingCourse] = useState(false);
  const [generatedModules, setGeneratedModules] = useState<GeneratedModule[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<{
    indexed: boolean;
    chunks_indexed: number;
    task_state?: string;
  } | null>(null);
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stepIndex = STEPS.indexOf(step);

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
        const dt = new DataTransfer();
        pdfs.forEach((f) => dt.items.add(f));
        (fileInputRef as React.MutableRefObject<{ _pendingFiles?: File[] }>).current = {
          _pendingFiles: pdfs,
        };
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
      const course = await apiFetch<{ id: string }>("/api/v1/admin/courses", {
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

      const ref = fileInputRef as React.MutableRefObject<{ _pendingFiles?: File[] }>;
      const pendingFiles = ref.current?._pendingFiles || [];
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
      }

      setStep("generate");
    } catch {
      setInfoErrors({ title_fr: t("info.titleFrRequired") });
    } finally {
      setIsCreatingCourse(false);
    }
  }, [courseInfo, getAuthHeaders, t]);

  const generateSyllabus = useCallback(async () => {
    if (!courseId) return;
    setIsGenerating(true);
    setGenerateError(null);

    try {
      const result = await apiFetch<{ modules: GeneratedModule[]; count: number }>(
        `/api/v1/admin/courses/${courseId}/generate-structure`,
        {
          method: "POST",
          body: JSON.stringify({
            estimated_hours: courseInfo.estimated_hours,
          }),
        }
      );
      setGeneratedModules(result.modules);
    } catch {
      setGenerateError(t("generate.error"));
    } finally {
      setIsGenerating(false);
    }
  }, [courseId, courseInfo, t]);

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
          task?: { state: string };
        }>(`/api/v1/admin/courses/${courseId}/index-status${params}`);

        setIndexStatus({
          indexed: status.indexed,
          chunks_indexed: status.chunks_indexed,
          task_state: status.task?.state,
        });

        if (status.indexed && status.chunks_indexed > 0) {
          setIsIndexing(false);
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
  }, [courseId, isIndexing, taskId, t]);

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

  const canGoNext = (): boolean => {
    if (step === "upload") return files.filter((f) => f.status === "uploaded").length > 0;
    if (step === "info") return courseInfo.title_fr.trim().length > 0 && courseInfo.title_en.trim().length > 0;
    if (step === "generate") return generatedModules.length > 0;
    if (step === "index") return !!(indexStatus?.indexed && indexStatus.chunks_indexed > 0);
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

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <div className="flex items-center justify-between border-b px-4 py-3 shrink-0">
        <h2 className="text-lg font-semibold">{t("title")}</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("close")}>
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

                <div className="space-y-1.5">
                  <Label>{t("info.domain")}</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {DOMAIN_OPTIONS.map((opt) => {
                      const sel = courseInfo.course_domain.includes(opt);
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() =>
                            setCourseInfo((p) => ({
                              ...p,
                              course_domain: sel
                                ? p.course_domain.filter((v) => v !== opt)
                                : [...p.course_domain, opt],
                            }))
                          }
                          className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors min-h-[32px] ${
                            sel
                              ? "bg-teal-600 text-white hover:bg-teal-700"
                              : "bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200"
                          }`}
                        >
                          {tTax(`domains.${opt}`)}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label>{t("info.level")}</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {LEVEL_OPTIONS.map((opt) => {
                      const sel = courseInfo.course_level.includes(opt);
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() =>
                            setCourseInfo((p) => ({
                              ...p,
                              course_level: sel
                                ? p.course_level.filter((v) => v !== opt)
                                : [...p.course_level, opt],
                            }))
                          }
                          className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors min-h-[32px] ${
                            sel
                              ? "bg-teal-600 text-white hover:bg-teal-700"
                              : "bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200"
                          }`}
                        >
                          {tTax(`levels.${opt}`)}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label>{t("info.audience")}</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {AUDIENCE_OPTIONS.map((opt) => {
                      const sel = courseInfo.audience_type.includes(opt);
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() =>
                            setCourseInfo((p) => ({
                              ...p,
                              audience_type: sel
                                ? p.audience_type.filter((v) => v !== opt)
                                : [...p.audience_type, opt],
                            }))
                          }
                          className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors min-h-[32px] ${
                            sel
                              ? "bg-teal-600 text-white hover:bg-teal-700"
                              : "bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200"
                          }`}
                        >
                          {tTax(`audience_types.${opt}`)}
                        </button>
                      );
                    })}
                  </div>
                </div>

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
                <div className="flex flex-col items-center gap-3 py-8">
                  <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                  <p className="text-sm text-muted-foreground">{t("generate.generating")}</p>
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

              {!isIndexing && !indexStatus?.indexed && (
                <Button onClick={startIndexation} className="w-full min-h-11" disabled={isIndexing}>
                  <Database className="mr-2 h-4 w-4" />
                  {t("index.button")}
                </Button>
              )}

              {isIndexing && (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                    <p className="text-sm text-muted-foreground">
                      {indexStatus?.task_state === "INDEXING"
                        ? t("index.taskRunning")
                        : indexStatus?.task_state === "EXTRACTING"
                        ? t("index.taskRunning")
                        : t("index.taskPending")}
                    </p>
                  </div>
                  <Progress value={indexStatus?.chunks_indexed ? 70 : 20} className="h-2" />
                  {indexStatus && indexStatus.chunks_indexed > 0 && (
                    <p className="text-xs text-muted-foreground">
                      {t("index.chunksIndexed", { count: indexStatus.chunks_indexed })}
                    </p>
                  )}
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
                  <CheckCircle2 className="h-5 w-5 text-green-600" />
                  <div>
                    <p className="text-sm font-medium text-green-700 dark:text-green-400">
                      {t("index.indexed")}
                    </p>
                    <p className="text-xs text-green-600 dark:text-green-500">
                      {t("index.chunksIndexed", { count: indexStatus.chunks_indexed })}
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
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("publish.summary.modules")}</span>
                    <span className="font-medium">{generatedModules.length}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("publish.summary.chunks")}</span>
                    <span className="font-medium">{indexStatus?.chunks_indexed ?? 0}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("publish.summary.status")}</span>
                    <Badge variant="outline" className="text-amber-600 border-amber-300">
                      draft
                    </Badge>
                  </div>
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
  );
}
