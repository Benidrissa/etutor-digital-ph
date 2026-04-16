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
  Target,
  Wand2,
  GripVertical,
  AlertCircle,
  Clock,
  ChevronDown,
  StopCircle,
  RotateCcw,
  BookOpen,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
} from "@/components/ui/alert-dialog";
import {
  type UploadedFile,
  type GeneratedModule,
  type IndexStatus,
  createAdminCourse,
  uploadCourseResource,
  deleteCourseResource,
  getCourseResources,
  getAdminCourse,
  triggerSyllabusGeneration,
  regenerateSyllabusApi,
  getGenerationStatus,
  triggerIndexation,
  getIndexStatusApi,
  cancelIndexationApi,
  reindexImagesApi,
  updateAdminCourse,
  publishAdminCourse,
  suggestCourseMetadata,
  formatBytes,
} from "@/lib/api-course-admin";
import { getCourseTaxonomy, type TaxonomyItem } from "@/lib/api";
import { SyllabusVisualEditor } from "@/components/admin/syllabus-visual-editor";
import { LessonPreviewStep } from "@/components/admin/lesson-preview-step";

// ── Step types ────────────────────────────────────────────────────────

type AIWizardStep =
  | "upload"
  | "objectives"
  | "ai_proposal"
  | "generate"
  | "syllabus_edit"
  | "lesson_preview"
  | "publish";

const AI_STEPS: AIWizardStep[] = [
  "upload",
  "objectives",
  "ai_proposal",
  "generate",
  "syllabus_edit",
  "lesson_preview",
  "publish",
];

const STEP_ICONS: Record<AIWizardStep, React.ReactNode> = {
  upload: <Upload className="h-4 w-4" />,
  objectives: <Target className="h-4 w-4" />,
  ai_proposal: <Wand2 className="h-4 w-4" />,
  generate: <Sparkles className="h-4 w-4" />,
  syllabus_edit: <GripVertical className="h-4 w-4" />,
  lesson_preview: <BookOpen className="h-4 w-4" />,
  publish: <Rocket className="h-4 w-4" />,
};

// ── Shared sub-components ─────────────────────────────────────────────

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

function ETALabel({ seconds, t }: { seconds: number | undefined; t: ReturnType<typeof useTranslations> }) {
  if (seconds === undefined || seconds <= 0) return null;
  if (seconds < 60) return <span>{t("index.etaSeconds", { seconds })}</span>;
  return <span>{t("index.etaMinutes", { minutes: Math.ceil(seconds / 60) })}</span>;
}

// ── Props ─────────────────────────────────────────────────────────────

interface AICourseWizardProps {
  onClose: () => void;
  onCourseCreated: () => void;
  resumeCourseId?: string;
  resumeCreationStep?: string;
  organizationId?: string;
}

export function AICourseWizard({
  onClose,
  onCourseCreated,
  resumeCourseId,
  resumeCreationStep,
  organizationId,
}: AICourseWizardProps) {
  const t = useTranslations("AdminCourses.wizard");
  const tAi = useTranslations("AdminCourses.aiWizard");
  const locale = useLocale();
  const queryClient = useQueryClient();

  // ── State ─────────────────────────────────────────────────────────
  const [step, setStep] = useState<AIWizardStep>("upload");
  const [isDragOver, setIsDragOver] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [courseId, setCourseId] = useState<string | null>(resumeCourseId ?? null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isFetchingExistingFiles, setIsFetchingExistingFiles] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Objectives state
  const [objectivesFr, setObjectivesFr] = useState("");
  const [objectivesEn, setObjectivesEn] = useState("");
  const [estimatedHours, setEstimatedHours] = useState(20);
  const [domainOptions, setDomainOptions] = useState<TaxonomyItem[]>([]);
  const [levelOptions, setLevelOptions] = useState<TaxonomyItem[]>([]);
  const [audienceOptions, setAudienceOptions] = useState<TaxonomyItem[]>([]);
  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);
  const [selectedLevels, setSelectedLevels] = useState<string[]>([]);
  const [selectedAudience, setSelectedAudience] = useState<string[]>([]);
  const [taxonomyError, setTaxonomyError] = useState(false);
  const [isSavingObjectives, setIsSavingObjectives] = useState(false);

  // AI proposal state
  const [proposedTitle, setProposedTitle] = useState({ fr: "", en: "" });
  const [proposedDescription, setProposedDescription] = useState({ fr: "", en: "" });
  const [isLoadingProposal, setIsLoadingProposal] = useState(false);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [isSavingProposal, setIsSavingProposal] = useState(false);

  // Generation state
  const [generatedModules, setGeneratedModules] = useState<GeneratedModule[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
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
  const generatePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [shouldForceGenerate, setShouldForceGenerate] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [showFreshConfirm, setShowFreshConfirm] = useState(false);

  // Indexation state
  const [taskId, setTaskId] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [indexStaleWarning, setIndexStaleWarning] = useState(false);
  const lastIndexProgressValueRef = useRef(0);
  const lastIndexProgressTimeRef = useRef<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Publish state
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishSummaryTitle, setPublishSummaryTitle] = useState<{ title_fr: string; title_en: string } | null>(null);
  const [publishSummaryIndexStatus, setPublishSummaryIndexStatus] = useState<IndexStatus | null>(null);
  const [publishSummaryResources, setPublishSummaryResources] = useState<Array<{ name: string }>>([]);
  const [publishSummaryModuleCount, setPublishSummaryModuleCount] = useState<number>(0);
  const [isFetchingPublishSummary, setIsFetchingPublishSummary] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);

  const stepIndex = AI_STEPS.indexOf(step);

  // ── Load taxonomy ──────────────────────────────────────────────────

  useEffect(() => {
    getCourseTaxonomy().then((tax) => {
      const domains = tax.domains ?? [];
      const levels = tax.levels ?? [];
      const audienceTypes = tax.audience_types ?? [];
      setDomainOptions(domains);
      setLevelOptions(levels);
      setAudienceOptions(audienceTypes);
      if (domains.length === 0 && levels.length === 0 && audienceTypes.length === 0) {
        setTaxonomyError(true);
      }
    }).catch((err) => {
      console.error("[ai-course-wizard] Failed to load taxonomy:", err);
      setTaxonomyError(true);
    });
  }, []);

  // ── Hydrate on resume ─────────────────────────────────────────────

  useEffect(() => {
    if (!resumeCourseId) return;
    setIsFetchingExistingFiles(true);

    const hydrate = async () => {
      try {
        await getAdminCourse(resumeCourseId);

        if (resumeCreationStep === "generating") {
          // Task might still be running — go to generate step, polling will pick it up
          setStep("generate");
          // Check if task is still active or already done
          const genStatus = await getGenerationStatus(resumeCourseId);
          if (genStatus.modules && genStatus.modules.length > 0) {
            setGeneratedModules(genStatus.modules);
            // If task is done (modules exist), go to syllabus_edit
            if (genStatus.creation_step === "generated") {
              setStep("syllabus_edit");
            }
          }
          // If task is still active, start polling
          if (genStatus.task && ["PENDING", "STARTED", "RETRY"].includes(genStatus.task.state)) {
            setIsGenerating(true);
            setGenerateTaskId(genStatus.task.id ?? null);
            setGenerationStartTime(Date.now());
          } else if (genStatus.creation_step === "generating") {
            // Task is dead but creation_step never reset — enable force on next generate
            setShouldForceGenerate(true);
          }
        } else if (resumeCreationStep === "generated") {
          // Generation done — fetch modules and go to syllabus_edit
          const genStatus = await getGenerationStatus(resumeCourseId);
          if (genStatus.modules && genStatus.modules.length > 0) {
            setGeneratedModules(genStatus.modules);
            setStep("syllabus_edit");
          } else {
            setStep("generate");
          }
        } else if (resumeCreationStep === "indexing" || resumeCreationStep === "indexed") {
          setStep("publish");
        } else if (resumeCreationStep === "published") {
          setStep("publish");
        }
      } catch {
        // fallback
      } finally {
        setIsFetchingExistingFiles(false);
      }
    };

    hydrate();
  }, [resumeCourseId, resumeCreationStep]);

  // Fetch existing files when on upload step with a courseId
  useEffect(() => {
    if (step !== "upload" || !courseId) return;
    setIsFetchingExistingFiles(true);
    getCourseResources(courseId)
      .then((data) => {
        const serverFiles: UploadedFile[] = (data.files ?? []).map((f) => ({
          name: f.name,
          size_bytes: f.size_bytes,
          status: "uploaded" as const,
        }));
        setFiles((prev) => {
          const localNames = new Set(prev.map((f) => f.name));
          const toAdd = serverFiles.filter((f) => !localNames.has(f.name));
          return [...prev, ...toAdd];
        });
      })
      .catch(() => {})
      .finally(() => setIsFetchingExistingFiles(false));
  }, [step, courseId]);

  // ── File handling (reuses shared API wrappers) ────────────────────

  const uploadFile = useCallback(
    async (file: File) => {
      if (!courseId) return;
      setFiles((prev) =>
        prev.map((f) => (f.name === file.name ? { ...f, status: "uploading" as const } : f))
      );
      const result = await uploadCourseResource(courseId, file);
      if (!result.ok) {
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "error" as const, error: result.error } : f
          )
        );
        return;
      }
      setFiles((prev) =>
        prev.map((f) => (f.name === file.name ? { ...f, status: "uploaded" as const } : f))
      );

      // Check if backend auto-triggered indexation (AI-assisted mode)
      if (!isIndexing) {
        try {
          const status = await getIndexStatusApi(courseId);
          if (status.task && ["PENDING", "STARTED", "RETRY"].includes(status.task.state)) {
            setTaskId(status.task.id ?? null);
            setIsIndexing(true);
            lastIndexProgressTimeRef.current = Date.now();
          }
        } catch {
          // ignore — indexation check is best-effort
        }
      }
    },
    [courseId, isIndexing]
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
            newEntries.some((n) => n.name === f.name) ? { ...f, status: "uploaded" as const } : f
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
      handleFiles(Array.from(e.dataTransfer.files));
    },
    [handleFiles]
  );

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      handleFiles(Array.from(e.target.files || []));
      e.target.value = "";
    },
    [handleFiles]
  );

  const removeFile = useCallback(
    async (name: string) => {
      if (courseId) {
        await deleteCourseResource(courseId, name);
      }
      setFiles((prev) => prev.filter((f) => f.name !== name));
    },
    [courseId]
  );

  // ── Create course (on first Next from upload) ─────────────────────

  const createCourse = useCallback(async () => {
    if (courseId) {
      // Already created, just advance
      setStep("objectives");
      return;
    }

    try {
      // Create a placeholder course with AI-assisted mode
      const course = await createAdminCourse({
        title_fr: "Nouveau cours (AI)",
        title_en: "New course (AI)",
        creation_mode: "ai_assisted",
        organization_id: organizationId,
      });
      setCourseId(course.id);

      // Upload pending files
      for (const file of pendingFiles) {
        await uploadCourseResource(course.id, file);
      }
      if (pendingFiles.length > 0) {
        setFiles((prev) => prev.map((f) => ({ ...f, status: "uploaded" as const })));
        setPendingFiles([]);
      }

      setStep("objectives");
    } catch {
      // Stay on upload step
    }
  }, [courseId, pendingFiles]);

  // ── Objectives save ────────────────────────────────────────────────

  const saveObjectives = useCallback(async () => {
    if (!courseId) return;
    setIsSavingObjectives(true);
    try {
      const objFr = objectivesFr.split("\n").map(s => s.trim()).filter(Boolean);
      const objEn = objectivesEn.split("\n").map(s => s.trim()).filter(Boolean);
      await updateAdminCourse(courseId, {
        objectives_json: { fr: objFr, en: objEn },
        course_domain: selectedDomains,
        course_level: selectedLevels,
        audience_type: selectedAudience,
        estimated_hours: estimatedHours,
      });
      setStep("ai_proposal");
    } catch {
      // stay on step
    } finally {
      setIsSavingObjectives(false);
    }
  }, [courseId, objectivesFr, objectivesEn, selectedDomains, selectedLevels, selectedAudience, estimatedHours]);

  // ── AI Proposal ───────────────────────────────────────────────────

  const fetchProposal = useCallback(async () => {
    if (!courseId) return;
    setIsLoadingProposal(true);
    setProposalError(null);
    try {
      const result = await suggestCourseMetadata(courseId);
      setProposedTitle({ fr: result.title_fr, en: result.title_en });
      setProposedDescription({ fr: result.description_fr, en: result.description_en });
    } catch {
      setProposalError(tAi("aiProposal.error"));
    } finally {
      setIsLoadingProposal(false);
    }
  }, [courseId, tAi]);

  // Fetch proposal when entering the AI proposal step
  useEffect(() => {
    if (step !== "ai_proposal" || !courseId) return;
    // Only fetch if no proposal yet
    if (!proposedTitle.fr && !proposedTitle.en) {
      fetchProposal();
    }
  }, [step, courseId]); // eslint-disable-line react-hooks/exhaustive-deps

  const validateProposal = useCallback(async () => {
    if (!courseId) return;
    setIsSavingProposal(true);
    try {
      await updateAdminCourse(courseId, {
        title_fr: proposedTitle.fr,
        title_en: proposedTitle.en,
        description_fr: proposedDescription.fr || null,
        description_en: proposedDescription.en || null,
      });
      setStep("generate");
    } catch {
      // stay on step
    } finally {
      setIsSavingProposal(false);
    }
  }, [courseId, proposedTitle, proposedDescription]);

  // ── Generation polling (reuses shared API) ────────────────────────

  const generateSyllabus = useCallback(async (force?: boolean) => {
    if (!courseId || isGenerating) return;
    const useForce = force ?? shouldForceGenerate;
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
    setShouldForceGenerate(false);

    try {
      const result = await triggerSyllabusGeneration(courseId, 20, useForce);
      setGenerateTaskId(result.task_id);
    } catch {
      setGenerateError(t("generate.error"));
      setIsGenerating(false);
    }
  }, [courseId, isGenerating, shouldForceGenerate, t]);

  const regenerateSyllabus = useCallback(async (mode: "reuse" | "fresh") => {
    if (!courseId || isGenerating || isRegenerating) return;
    setIsRegenerating(true);
    setRegenerateError(null);
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
    setGeneratedModules([]);

    try {
      const result = await regenerateSyllabusApi(courseId, mode);
      setGenerateTaskId(result.task_id);
      setIsGenerating(true);
    } catch {
      setRegenerateError(t("generate.regenerateError"));
    } finally {
      setIsRegenerating(false);
    }
  }, [courseId, isGenerating, isRegenerating, t]);

  useEffect(() => {
    if (!courseId || !isGenerating || !generateTaskId) return;

    const poll = async () => {
      try {
        const status = await getGenerationStatus(courseId, generateTaskId);
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
          if (Date.now() - lastProgressTimeRef.current > 2 * 60 * 1000) {
            setShowTimeoutWarning(true);
          }
        }

        if (status.task?.state === "FAILURE" || status.task?.state === "REVOKED") {
          setGenerateError(t("generate.error"));
          setIsGenerating(false);
          return;
        }

        if (status.task?.state === "SUCCESS" || status.task?.state === "COMPLETE") {
          // Modules may be in meta.modules (during task) or status.modules (from DB)
          const modules = Array.isArray(meta.modules)
            ? meta.modules
            : Array.isArray(status.modules)
              ? status.modules
              : null;
          if (modules && modules.length > 0) {
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

  // ── Indexation polling (reuses shared API) ────────────────────────

  const startIndexation = useCallback(async () => {
    if (!courseId) return;
    setIsIndexing(true);
    setIndexError(null);
    setIndexStaleWarning(false);
    lastIndexProgressValueRef.current = 0;
    lastIndexProgressTimeRef.current = Date.now();

    try {
      const result = await triggerIndexation(courseId);
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
        const status = await getIndexStatusApi(courseId, taskId ?? undefined);

        setIndexStatus({
          indexed: status.indexed,
          chunks_indexed: status.chunks_indexed,
          images_indexed: status.images_indexed,
          task: status.task,
        });

        const newProgress = status.task?.progress ?? 0;
        if (newProgress !== lastIndexProgressValueRef.current) {
          lastIndexProgressValueRef.current = newProgress;
          lastIndexProgressTimeRef.current = Date.now();
          setIndexStaleWarning(false);
        } else if (lastIndexProgressTimeRef.current !== null) {
          const staleSince = Date.now() - lastIndexProgressTimeRef.current;
          if (staleSince > 60 * 1000) setIndexStaleWarning(true);
        }

        if (status.task?.state === "SUCCESS" || status.task?.state === "COMPLETE") {
          setIndexStatus({ indexed: true, chunks_indexed: status.chunks_indexed, images_indexed: status.images_indexed, task: status.task });
          setIsIndexing(false);
          setIndexStaleWarning(false);
          queryClient.invalidateQueries({ queryKey: ["admin-courses"] });
          return;
        }

        if (status.task?.state === "FAILURE" || status.task?.state === "REVOKED") {
          setIndexError(t("index.error"));
          setIsIndexing(false);
          setIndexStaleWarning(false);
          return;
        }

        if (lastIndexProgressTimeRef.current !== null && Date.now() - lastIndexProgressTimeRef.current > 2 * 60 * 1000) {
          setIndexError(t("index.error"));
          setIsIndexing(false);
          return;
        }

        pollRef.current = setTimeout(poll, 3000);
      } catch {
        pollRef.current = setTimeout(poll, 5000);
      }
    };

    if (lastIndexProgressTimeRef.current === null) lastIndexProgressTimeRef.current = Date.now();
    pollRef.current = setTimeout(poll, 2000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [courseId, isIndexing, taskId, t, queryClient]);

  const cancelIndexation = useCallback(async () => {
    if (!courseId) return;
    if (pollRef.current) clearTimeout(pollRef.current);
    try {
      await cancelIndexationApi(courseId);
      setIsIndexing(false);
      setIndexStaleWarning(false);
      setTaskId(null);
      setIndexStatus(null);
      lastIndexProgressValueRef.current = 0;
      lastIndexProgressTimeRef.current = null;
    } catch {
      // ignore
    }
  }, [courseId]);

  const reindexImages = useCallback(async () => {
    if (!courseId) return;
    try {
      const result = await reindexImagesApi(courseId);
      setTaskId(result.task_id);
      setIsIndexing(true);
    } catch {
      // ignore
    }
  }, [courseId]);

  // ── Publish ───────────────────────────────────────────────────────

  useEffect(() => {
    if (step !== "publish" || !courseId) return;
    setIsFetchingPublishSummary(true);
    Promise.all([
      getAdminCourse(courseId),
      getIndexStatusApi(courseId),
      getCourseResources(courseId),
      getGenerationStatus(courseId),
    ])
      .then(([courseData, statusData, resourcesData, modulesData]) => {
        setPublishSummaryTitle({ title_fr: courseData.title_fr, title_en: courseData.title_en });
        setPublishSummaryModuleCount(modulesData.modules_count ?? 0);
        setPublishSummaryIndexStatus(statusData);
        setPublishSummaryResources(resourcesData.files ?? []);
      })
      .catch(() => {})
      .finally(() => setIsFetchingPublishSummary(false));
  }, [step, courseId]);

  const publishCourse = useCallback(async () => {
    if (!courseId) return;
    setIsPublishing(true);
    setPublishError(null);
    try {
      await publishAdminCourse(courseId);
      setPublishSuccess(true);
      queryClient.invalidateQueries({ queryKey: ["admin-courses"] });
      onCourseCreated();
    } catch {
      setPublishError(t("publish.error"));
    } finally {
      setIsPublishing(false);
    }
  }, [courseId, queryClient, onCourseCreated, t]);

  // ── Navigation ────────────────────────────────────────────────────

  const handleClose = useCallback(() => {
    if (isIndexing || isGenerating) {
      setShowCloseConfirm(true);
      return;
    }
    onClose();
  }, [isIndexing, isGenerating, onClose]);

  const canGoNext = (): boolean => {
    if (step === "upload") return files.filter((f) => f.status === "uploaded").length > 0;
    if (step === "objectives") return objectivesFr.trim().length > 0 || objectivesEn.trim().length > 0;
    if (step === "ai_proposal") return proposedTitle.fr.trim().length > 0 && proposedTitle.en.trim().length > 0;
    if (step === "generate") return generatedModules.length > 0;
    if (step === "syllabus_edit") return generatedModules.length > 0;
    if (step === "lesson_preview") return true; // Optional step — always skippable
    return false;
  };

  const handleNext = () => {
    if (step === "upload") {
      createCourse();
      return;
    }
    if (step === "objectives") {
      saveObjectives();
      return;
    }
    if (step === "ai_proposal") {
      validateProposal();
      return;
    }
    const idx = AI_STEPS.indexOf(step);
    if (idx < AI_STEPS.length - 1) setStep(AI_STEPS[idx + 1]);
  };

  const skipToPublish = () => setStep("publish");

  const handleBack = () => {
    if (isGenerating || isIndexing) return;
    const idx = AI_STEPS.indexOf(step);
    if (idx > 0) setStep(AI_STEPS[idx - 1]);
  };

  // ── Helpers ───────────────────────────────────────────────────────

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
      case "extracting_images":
      case "EXTRACTING_IMAGES": return t("index.stepExtractingImages");
      default: return t("index.taskPending");
    }
  };

  const taskProg = indexStatus?.task;
  const progressValue = taskProg?.progress ?? (indexStatus?.indexed ? 100 : 0);

  // ── Render ────────────────────────────────────────────────────────

  return (
    <>
      <div className="fixed inset-0 z-50 flex flex-col bg-background">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3 shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">{tAi("title")}</h2>
            {/* Persistent indexation badge */}
            {isIndexing && step !== "syllabus_edit" && (
              <Badge className="gap-1 bg-amber-100 text-amber-800 border-amber-300 hover:bg-amber-100 dark:bg-amber-900 dark:text-amber-200 text-xs">
                <Database className="h-3 w-3 animate-pulse" />
                {tAi("indexingBadge")}
              </Badge>
            )}
            {indexStatus?.indexed && !isIndexing && (
              <Badge className="gap-1 bg-green-100 text-green-800 border-green-300 hover:bg-green-100 dark:bg-green-900 dark:text-green-200 text-xs">
                <CheckCircle2 className="h-3 w-3" />
                {tAi("indexedBadge")}
              </Badge>
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={handleClose} aria-label={t("close")}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        {/* Step indicator */}
        <div className="border-b px-4 py-3 shrink-0">
          <div className="flex items-center gap-1 overflow-x-auto">
            {AI_STEPS.map((s, i) => (
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
                    STEP_ICONS[s]
                  )}
                  <span className="hidden sm:inline">{tAi(`steps.${s}`)}</span>
                </div>
                {i < AI_STEPS.length - 1 && (
                  <div className={`h-px w-4 ${i < stepIndex ? "bg-primary/40" : "bg-border"}`} />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto max-w-2xl">

            {/* ── UPLOAD STEP ─────────────────────────────────────── */}
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

                {isFetchingExistingFiles && (
                  <div className="flex items-center justify-center py-4">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  </div>
                )}

                {files.length > 0 && (
                  <div className="space-y-2">
                    {files.map((f) => (
                      <div key={f.name} className="flex items-center gap-3 rounded-lg border bg-card p-3">
                        <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{f.name}</p>
                          <p className="text-xs text-muted-foreground">{formatBytes(f.size_bytes)}</p>
                        </div>
                        {f.status === "uploading" && (
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        )}
                        {f.status === "uploaded" && <CheckCircle2 className="h-4 w-4 text-green-600" />}
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

            {/* ── OBJECTIVES STEP ────────────────────────────────── */}
            {step === "objectives" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{tAi("objectives.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{tAi("objectives.description")}</p>
                </div>

                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="objectives_fr">{tAi("objectives.objectivesFr")}</Label>
                    <Textarea
                      id="objectives_fr"
                      value={objectivesFr}
                      onChange={(e) => setObjectivesFr(e.target.value)}
                      placeholder={tAi("objectives.objectivesFrPlaceholder")}
                      className="min-h-[100px] resize-none text-base"
                      rows={4}
                    />
                    <p className="text-xs text-muted-foreground">{tAi("objectives.objectivesHint")}</p>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="objectives_en">{tAi("objectives.objectivesEn")}</Label>
                    <Textarea
                      id="objectives_en"
                      value={objectivesEn}
                      onChange={(e) => setObjectivesEn(e.target.value)}
                      placeholder={tAi("objectives.objectivesEnPlaceholder")}
                      className="min-h-[100px] resize-none text-base"
                      rows={4}
                    />
                  </div>

                  {taxonomyError && (
                    <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {locale === "fr"
                        ? "Impossible de charger les catégories. Rechargez la page ou continuez sans."
                        : "Could not load categories. Reload the page or continue without."}
                    </div>
                  )}

                  {[
                    { label: tAi("objectives.domain"), options: domainOptions, selected: selectedDomains, setSelected: setSelectedDomains },
                    { label: tAi("objectives.level"), options: levelOptions, selected: selectedLevels, setSelected: setSelectedLevels },
                    { label: tAi("objectives.audience"), options: audienceOptions, selected: selectedAudience, setSelected: setSelectedAudience },
                  ].map(({ label, options, selected, setSelected }) => (
                    <div key={label} className="space-y-1.5">
                      <Label>{label}</Label>
                      <div className="flex flex-wrap gap-1.5">
                        {options.map((opt) => {
                          const sel = selected.includes(opt.value);
                          return (
                            <button
                              key={opt.value}
                              type="button"
                              onClick={() =>
                                setSelected(sel ? selected.filter((v) => v !== opt.value) : [...selected, opt.value])
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
                    <Label htmlFor="estimated_hours">{tAi("objectives.estimatedHours")}</Label>
                    <Input
                      id="estimated_hours"
                      type="number"
                      min={1}
                      max={500}
                      value={estimatedHours}
                      onChange={(e) => setEstimatedHours(parseInt(e.target.value) || 20)}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── AI PROPOSAL STEP ───────────────────────────────── */}
            {step === "ai_proposal" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{tAi("aiProposal.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{tAi("aiProposal.description")}</p>
                </div>

                {isLoadingProposal && (
                  <div className="flex flex-col items-center justify-center py-12 gap-3">
                    <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                    <p className="text-sm text-muted-foreground">{tAi("aiProposal.loading")}</p>
                  </div>
                )}

                {proposalError && (
                  <div className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                    <div className="flex items-center gap-2 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {proposalError}
                    </div>
                    <Button variant="outline" size="sm" onClick={fetchProposal} className="self-start min-h-[44px]">
                      <Wand2 className="mr-2 h-4 w-4" />
                      {tAi("aiProposal.retry")}
                    </Button>
                  </div>
                )}

                {!isLoadingProposal && !proposalError && (
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="proposed_title_fr">{tAi("aiProposal.titleFr")}</Label>
                      <Input
                        id="proposed_title_fr"
                        value={proposedTitle.fr}
                        onChange={(e) => setProposedTitle((p) => ({ ...p, fr: e.target.value }))}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="proposed_title_en">{tAi("aiProposal.titleEn")}</Label>
                      <Input
                        id="proposed_title_en"
                        value={proposedTitle.en}
                        onChange={(e) => setProposedTitle((p) => ({ ...p, en: e.target.value }))}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="proposed_desc_fr">{tAi("aiProposal.descriptionFr")}</Label>
                      <Textarea
                        id="proposed_desc_fr"
                        value={proposedDescription.fr}
                        onChange={(e) => setProposedDescription((p) => ({ ...p, fr: e.target.value }))}
                        className="min-h-[80px] resize-none text-base"
                        rows={3}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="proposed_desc_en">{tAi("aiProposal.descriptionEn")}</Label>
                      <Textarea
                        id="proposed_desc_en"
                        value={proposedDescription.en}
                        onChange={(e) => setProposedDescription((p) => ({ ...p, en: e.target.value }))}
                        className="min-h-[80px] resize-none text-base"
                        rows={3}
                      />
                    </div>

                    <Button variant="outline" onClick={fetchProposal} disabled={isLoadingProposal} className="w-full min-h-[44px]">
                      <Wand2 className="mr-2 h-4 w-4" />
                      {tAi("aiProposal.regenerate")}
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* ── GENERATE STEP ────────────────────────────────────── */}
            {step === "generate" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("generate.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("generate.description")}</p>
                </div>

                <AttachedResources files={files} t={t} />

                {generatedModules.length === 0 && !isGenerating && (
                  <Button onClick={() => generateSyllabus()} className="w-full min-h-11" disabled={isGenerating}>
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
                          {generationStep ? getGenerateStepLabel(generationStep) : generateTaskState ? t("generate.taskRunning") : t("generate.taskPending")}
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
                  <div className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                    <div className="flex items-center gap-2 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {generateError}
                    </div>
                    <Button variant="outline" size="sm" onClick={() => generateSyllabus()} className="self-start min-h-[44px]">
                      <Sparkles className="mr-2 h-4 w-4" />
                      {t("generate.retry")}
                    </Button>
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
                        <div key={m.id} className="flex items-center gap-3 rounded-lg border bg-card p-3">
                          <Badge variant="outline" className="shrink-0 text-xs">M{m.module_number}</Badge>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">{m.title_fr}</p>
                            <p className="truncate text-xs text-muted-foreground">{m.title_en}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                    {!isGenerating && (
                      <div className="flex flex-col gap-2 pt-1">
                        <Button variant="outline" size="sm" onClick={() => regenerateSyllabus("reuse")} disabled={isRegenerating} className="min-h-[44px] w-full">
                          {isRegenerating ? <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" /> : <Sparkles className="mr-2 h-4 w-4" />}
                          {t("generate.regenerate")}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setShowFreshConfirm(true)} disabled={isRegenerating} className="min-h-[44px] w-full border-destructive/50 text-destructive hover:bg-destructive/5 hover:text-destructive">
                          <Trash2 className="mr-2 h-4 w-4" />
                          {t("generate.regenerateFresh")}
                        </Button>
                        {regenerateError && (
                          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                            <AlertCircle className="h-4 w-4 shrink-0" />
                            {regenerateError}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── SYLLABUS EDIT STEP (placeholder) ────────────────── */}
            {step === "syllabus_edit" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{tAi("syllabusEdit.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{tAi("syllabusEdit.description")}</p>
                </div>

                {/* If indexation not started yet, start it now */}
                {!isIndexing && !indexStatus?.indexed && courseId && (
                  <div className="space-y-3">
                    <p className="text-sm text-muted-foreground">{tAi("syllabusEdit.indexNeeded")}</p>
                    <Button onClick={startIndexation} className="w-full min-h-11">
                      <Database className="mr-2 h-4 w-4" />
                      {t("index.button")}
                    </Button>
                  </div>
                )}

                {/* Indexation progress (inline, not a separate step) */}
                {isIndexing && (
                  <div className="rounded-lg border bg-card p-4 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent shrink-0" />
                        <p className="text-sm font-medium">
                          {taskProg ? (taskProg.state === "EXTRACTING_IMAGES" ? t("index.stepExtractingImages") : getStepLabel(taskProg.step)) : t("index.taskPending")}
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
                        <span>{t("index.filesProgress", { current: taskProg.files_processed, total: taskProg.files_total })}</span>
                      )}
                    </div>
                    <Button variant="outline" size="sm" onClick={cancelIndexation} className="w-full min-h-[44px] border-destructive/50 text-destructive hover:bg-destructive/5 hover:text-destructive">
                      <StopCircle className="mr-2 h-4 w-4" />
                      {t("index.cancelIndexation")}
                    </Button>
                  </div>
                )}

                {indexStatus?.indexed && !isIndexing && (
                  <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    <div>
                      <p className="text-sm font-medium text-green-700 dark:text-green-400">{t("index.indexed")}</p>
                      <p className="text-xs text-green-600 dark:text-green-500">
                        {indexStatus.images_indexed && indexStatus.images_indexed > 0
                          ? t("index.chunksAndImagesIndexed", { chunks: indexStatus.chunks_indexed, images: indexStatus.images_indexed })
                          : t("index.chunksIndexed", { count: indexStatus.chunks_indexed })}
                      </p>
                    </div>
                  </div>
                )}

                {indexError && !isIndexing && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {indexError}
                    </div>
                    <Button onClick={startIndexation} variant="outline" size="sm" className="w-full min-h-[44px]">
                      <RotateCcw className="mr-2 h-4 w-4" />
                      {t("index.retryIndexation")}
                    </Button>
                  </div>
                )}

                {/* Visual syllabus editor */}
                {courseId && (
                  <SyllabusVisualEditor
                    courseId={courseId}
                    fetchOnMount
                  />
                )}
              </div>
            )}

            {/* ── LESSON PREVIEW STEP ───────────────────────────────── */}
            {step === "lesson_preview" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{tAi("lessonPreview.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{tAi("lessonPreview.description")}</p>
                </div>

                {courseId && <LessonPreviewStep courseId={courseId} />}

                <p className="text-xs text-muted-foreground text-center">
                  {tAi("lessonPreview.skipHint")}
                </p>
              </div>
            )}

            {/* ── PUBLISH STEP ─────────────────────────────────────── */}
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
                            <span className="font-medium text-right">{t("publish.summary.resourcesCount", { count: publishSummaryResources.length })}</span>
                          </div>
                        )}
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">{t("publish.summary.status")}</span>
                          <Badge variant="outline" className="text-amber-600 border-amber-300">draft</Badge>
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
                    <Button onClick={onClose} className="mt-2">{t("close")}</Button>
                  </div>
                ) : (
                  <>
                    {publishError && (
                      <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                        <AlertCircle className="h-4 w-4 shrink-0" />
                        {publishError}
                      </div>
                    )}
                    <Button onClick={publishCourse} className="w-full min-h-11" disabled={isPublishing}>
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

        {/* Footer navigation */}
        {!publishSuccess && (
          <div className="flex items-center justify-between border-t bg-background px-4 py-3 shrink-0">
            <Button variant="outline" onClick={handleBack} disabled={stepIndex === 0 || isGenerating || isIndexing} className="min-h-11">
              <ChevronLeft className="mr-1 h-4 w-4" />
              {t("back")}
            </Button>
            <div className="flex items-center gap-2">
              {(step === "generate" || step === "syllabus_edit" || step === "lesson_preview") && canGoNext() && (
                <Button variant="ghost" onClick={skipToPublish} className="min-h-11 text-muted-foreground">
                  {tAi("skipToPublish")}
                  <Rocket className="ml-1 h-4 w-4" />
                </Button>
              )}
              {step !== "publish" && (
                <Button onClick={handleNext} disabled={!canGoNext() || isGenerating} className="min-h-11">
                  {t("next")}
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Close confirmation dialog */}
      <AlertDialog open={showCloseConfirm} onOpenChange={setShowCloseConfirm}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("closeWhileRunning.title")}</AlertDialogTitle>
          <AlertDialogDescription>{t("closeWhileRunning.description")}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <Button variant="outline" onClick={() => setShowCloseConfirm(false)}>{t("closeWhileRunning.cancel")}</Button>
            <Button onClick={() => { setShowCloseConfirm(false); onClose(); }}>{t("closeWhileRunning.confirmClose")}</Button>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      {/* Fresh regenerate confirmation */}
      <AlertDialog open={showFreshConfirm} onOpenChange={setShowFreshConfirm}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("generate.regenerateFreshConfirmTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("generate.regenerateFreshConfirmDescription")}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <Button variant="outline" onClick={() => setShowFreshConfirm(false)}>{t("generate.regenerateFreshConfirmCancel")}</Button>
            <Button variant="destructive" onClick={() => { setShowFreshConfirm(false); regenerateSyllabus("fresh"); }}>{t("generate.regenerateFreshConfirmAction")}</Button>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
