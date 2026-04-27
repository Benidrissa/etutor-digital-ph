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
  Link as LinkIcon,
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
  getAdminCourse,
  getCourseResources,
  triggerSyllabusGeneration,
  regenerateSyllabusApi,
  getGenerationStatus,
  triggerIndexation,
  getIndexStatusApi,
  cancelIndexationApi,
  reindexImagesApi,
  relinkImagesApi,
  updateAdminCourse,
  publishAdminCourse,
  suggestCourseMetadata,
  formatBytes,
} from "@/lib/api-course-admin";
import { getCourseTaxonomy, type TaxonomyItem } from "@/lib/api";
import { SyllabusVisualEditor } from "@/components/admin/syllabus-visual-editor";
import { LessonPreviewStep } from "@/components/admin/lesson-preview-step";
import {
  CourseResourceUploadStep,
  useCourseResourceUpload,
} from "@/components/admin/course-resource-upload-step";

const EXTRACTING_STATUSES = new Set(["pending", "extracting"]);

// ── Step types ────────────────────────────────────────────────────────

type AIWizardStep =
  | "upload"
  | "objectives"
  | "ai_proposal"
  | "generate"
  | "syllabus_edit"
  | "lesson_preview"
  | "indexation"
  | "linker"
  | "publish";

const AI_STEPS: AIWizardStep[] = [
  "upload",
  "objectives",
  "ai_proposal",
  "generate",
  "syllabus_edit",
  "lesson_preview",
  // Dedicated indexation step so the Texte/Images recap is visible
  // as its own phase rather than buried inside syllabus_edit (#2041).
  "indexation",
  // Dedicated linker step — splits the chunk↔image join from the
  // text+image extraction phase. Lets the admin see the link count and
  // hit "Relancer le linker" without paying for re-embedding (#2044).
  "linker",
  "publish",
];

const STEP_ICONS: Record<AIWizardStep, React.ReactNode> = {
  upload: <Upload className="h-4 w-4" />,
  objectives: <Target className="h-4 w-4" />,
  ai_proposal: <Wand2 className="h-4 w-4" />,
  generate: <Sparkles className="h-4 w-4" />,
  syllabus_edit: <GripVertical className="h-4 w-4" />,
  lesson_preview: <BookOpen className="h-4 w-4" />,
  indexation: <Database className="h-4 w-4" />,
  linker: <LinkIcon className="h-4 w-4" />,
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

// Stages where the celery task is still working on the TEXT phase. After
// these, the task moves into image extraction/linking.
const TEXT_STAGES = new Set([
  "PENDING",
  "STARTED",
  "EXTRACTING",
  "CHUNKING",
  "EMBEDDING",
  "STORING",
]);

// Stages where the IMAGE phase has begun (text is done by now).
const IMAGE_STAGES = new Set(["EXTRACTING_IMAGES", "LINKING_IMAGES"]);

// Text+images extraction has hit COMPLETE/SUCCESS. Linker may not have run.
// This is the gate for advancing past the "indexation" step (#2044).
function isExtractionComplete(indexStatus: IndexStatus | null): boolean {
  if (!indexStatus) return false;
  const taskState = indexStatus.task?.state;
  if (taskState === "COMPLETE" || taskState === "SUCCESS") return true;

  // No active task and we have indexed data → done.
  if (
    !taskState &&
    indexStatus.indexed &&
    (indexStatus.chunks_indexed ?? 0) > 0
  )
    return true;

  // Stale-task heuristic (#2051): if a task is "still running" but reports
  // estimated_seconds_remaining=0 with progress<100 and we already have
  // chunks+images in the DB, the celery worker has crashed silently. Fall
  // through to "effectively done" so the admin can advance to the linker
  // step (which has its own recovery path) instead of being stranded.
  const eta = indexStatus.task?.estimated_seconds_remaining;
  const progress = indexStatus.task?.progress ?? 0;
  if (
    indexStatus.indexed &&
    (indexStatus.chunks_indexed ?? 0) > 0 &&
    (indexStatus.images_indexed ?? 0) > 0 &&
    eta === 0 &&
    progress < 100
  )
    return true;

  return false;
}

// Linker has populated source_image_chunks, OR there were no images to link.
// This is the publish gate AND the "linker" step gate. PDFs with no figures
// legitimately have 0 images AND 0 links; that's still publishable. (#2035)
function isLinkerComplete(indexStatus: IndexStatus | null): boolean {
  if (!isExtractionComplete(indexStatus)) return false;
  const images = indexStatus?.images_indexed ?? 0;
  const links = indexStatus?.links_indexed ?? 0;
  return images === 0 || links > 0;
}

// Back-compat alias kept so the publish-button gate keeps the same name.
const isIndexationFullyComplete = isLinkerComplete;

// Single source of truth for shaping `setIndexStatus` payloads. Previously
// the polling tick + hydrate built this inline and silently dropped
// `links_indexed`, so every poll clobbered the field set by the SUCCESS
// branch and the wizard rendered "—" instead of the real link count (#2048).
type RawIndexStatus = {
  indexed: boolean;
  chunks_indexed: number;
  images_indexed?: number;
  links_indexed?: number;
  task?: IndexStatus["task"];
};
function buildIndexStatus(s: RawIndexStatus): IndexStatus {
  return {
    indexed: s.indexed,
    chunks_indexed: s.chunks_indexed,
    images_indexed: s.images_indexed,
    links_indexed: s.links_indexed,
    task: s.task,
  };
}

function IndexationRecap({
  indexStatus,
  isIndexing,
  progressValue,
  onCancel,
  t,
}: {
  indexStatus: IndexStatus | null;
  isIndexing: boolean;
  progressValue: number;
  onCancel?: () => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const taskState = indexStatus?.task?.state;
  const stepLabel = indexStatus?.task?.step_label;
  const eta = indexStatus?.task?.estimated_seconds_remaining;
  const chunks = indexStatus?.chunks_indexed ?? 0;
  const images = indexStatus?.images_indexed ?? 0;

  // Phase derivations based on the celery task state machine.
  const textRunning = !!taskState && TEXT_STAGES.has(taskState);
  const imagesRunning = !!taskState && IMAGE_STAGES.has(taskState);
  // The linker phase happens at the end of process_pdf_images, signalled
  // by celery state LINKING_IMAGES. The Liens row moved to a dedicated
  // "linker" step (#2044), so here we only treat LINKING_IMAGES as "image
  // extraction is done" — the linker substep gets its own UI.
  const linkingRunning = taskState === "LINKING_IMAGES";
  const extractionDone = isExtractionComplete(indexStatus);
  const textDone = extractionDone || imagesRunning || linkingRunning || chunks > 0;
  const imagesDone = extractionDone || linkingRunning;

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      {/* Texte row */}
      <div className="flex items-center gap-2">
        {textDone ? (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
        ) : textRunning ? (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        ) : (
          <div className="h-4 w-4 shrink-0 rounded-full border border-muted-foreground/40" />
        )}
        <p className="text-sm font-medium">{t("index.recap.textRow")}</p>
        <span className="ml-auto text-xs text-muted-foreground">
          {chunks > 0
            ? t("index.recap.chunksCount", { count: chunks })
            : "—"}
        </span>
      </div>

      {/* Images row */}
      <div className="flex items-center gap-2">
        {imagesDone ? (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
        ) : imagesRunning ? (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        ) : (
          <div className="h-4 w-4 shrink-0 rounded-full border border-muted-foreground/40" />
        )}
        <p className="text-sm font-medium">{t("index.recap.imagesRow")}</p>
        <span className="ml-auto text-xs text-muted-foreground">
          {images > 0
            ? t("index.recap.imagesCount", { count: images })
            : imagesRunning
            ? t("index.recap.imagesPending")
            : imagesDone
            ? t("index.recap.imagesNone")
            : "—"}
        </span>
      </div>

      {/* Live step label + ETA only while a phase is active */}
      {isIndexing && (
        <>
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="truncate">
              {stepLabel || t("index.taskPending")}
            </span>
            {eta !== undefined && eta > 0 && (
              <div className="flex items-center gap-1 shrink-0">
                <Clock className="h-3 w-3" />
                <ETALabel seconds={eta} t={t} />
              </div>
            )}
          </div>
          <Progress value={progressValue} className="h-2" />
          {onCancel && (
            <Button
              variant="outline"
              size="sm"
              onClick={onCancel}
              className="w-full min-h-[44px] border-destructive/50 text-destructive hover:bg-destructive/5 hover:text-destructive"
            >
              <StopCircle className="mr-2 h-4 w-4" />
              {t("index.cancelIndexation")}
            </Button>
          )}
        </>
      )}
    </div>
  );
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
  const [courseId, setCourseId] = useState<string | null>(resumeCourseId ?? null);
  // The upload state machine (queued/uploading/uploaded/error + dropzone +
  // file list + aggregate error banner) lives in a shared hook used by both
  // wizards — see course-resource-upload-step.tsx.
  const upload = useCourseResourceUpload({ courseId });
  const { files, setFiles, pendingFiles, uploadAllPending } = upload;

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

  // Extraction polling state (tracks background PDF extraction)
  const extractionPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const loadTaxonomy = useCallback(async () => {
    setTaxonomyError(false);
    try {
      const tax = await getCourseTaxonomy();
      const domains = tax.domains ?? [];
      const levels = tax.levels ?? [];
      const audienceTypes = tax.audience_types ?? [];
      setDomainOptions(domains);
      setLevelOptions(levels);
      setAudienceOptions(audienceTypes);
      if (domains.length === 0 && levels.length === 0 && audienceTypes.length === 0) {
        setTaxonomyError(true);
      }
    } catch (err) {
      console.error("[ai-course-wizard] Failed to load taxonomy:", err);
      setTaxonomyError(true);
    }
  }, []);

  useEffect(() => {
    loadTaxonomy();
  }, [loadTaxonomy]);

  // ── Hydrate on resume ─────────────────────────────────────────────

  useEffect(() => {
    if (!resumeCourseId) return;
    // The shared upload hook handles its own fetch-on-mount when courseId is
    // present, so we don't manage isFetchingExistingFiles here anymore.

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
          // creation_step alone is not trustworthy — the auto-chain may have
          // dispatched but silently failed, leaving chunks_indexed=0. Fetch
          // actual status and route based on real state.
          try {
            const status = await getIndexStatusApi(resumeCourseId);
            setIndexStatus(buildIndexStatus(status));
            const taskState = status.task?.state;
            if (taskState && ["PENDING", "STARTED", "RETRY"].includes(taskState)) {
              setTaskId(status.task?.id ?? null);
              setIsIndexing(true);
              lastIndexProgressTimeRef.current = Date.now();
              setStep("syllabus_edit");
            } else if (status.chunks_indexed > 0) {
              setStep("publish");
            } else {
              setStep("syllabus_edit");
            }
          } catch {
            setStep("syllabus_edit");
          }
        } else if (resumeCreationStep === "published") {
          setStep("publish");
        }
      } catch {
        // fallback
      }
    };

    hydrate();
  }, [resumeCourseId, resumeCreationStep]);

  // File state, dropzone handlers, and the upload state machine all live in
  // the shared `useCourseResourceUpload` hook (course-resource-upload-step.tsx).
  // Removed duplicate file-handling code that previously lived here.

  // ── Create course (on first Next from upload) ─────────────────────

  const createCourse = useCallback(async () => {
    // Already created and nothing pending → just advance.
    if (courseId && pendingFiles.length === 0) {
      setStep("objectives");
      return;
    }

    try {
      let activeCourseId = courseId;
      if (!activeCourseId) {
        const course = await createAdminCourse({
          title_fr: "Nouveau cours (AI)",
          title_en: "New course (AI)",
          creation_mode: "ai_assisted",
          organization_id: organizationId,
        });
        setCourseId(course.id);
        activeCourseId = course.id;
      }

      // Flush every locally-queued file. The hook returns ok=false if any
      // file failed; in that case we stay on the upload step so the user
      // can see the error banner and remove/retry.
      const result = await uploadAllPending(activeCourseId);
      if (!result.ok) return;

      setStep("objectives");
    } catch {
      // Stay on upload step; the hook surfaces upload errors via its banner.
    }
  }, [courseId, pendingFiles, organizationId, uploadAllPending]);

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

        setIndexStatus(buildIndexStatus(status));

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
          setIndexStatus(buildIndexStatus({ ...status, indexed: true }));
          setIsIndexing(false);
          setIndexStaleWarning(false);
          queryClient.invalidateQueries({ queryKey: ["admin-courses"] });
          // Auto-advance through the new linker step (#2044):
          //   indexation → linker (always)
          //   linker → publish iff the chunk↔image join produced rows
          //                     (or there were no images to link)
          // If the linker silently failed (images > 0, links === 0), stop on
          // the linker step so the admin can hit "Relancer le linker".
          const linksOk =
            (status.images_indexed ?? 0) === 0 ||
            (status.links_indexed ?? 0) > 0;
          setStep((s) => {
            if (s === "indexation") return "linker";
            if (s === "linker" && linksOk) return "publish";
            return s;
          });
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

  // ── Extraction polling (background PDF extraction) ─────────────────
  // Depend on a stable key derived from file statuses, not the full files
  // array — otherwise every setFiles call would re-run this effect and
  // constantly tear down + restart the timeout.
  const extractionKey = files
    .map((f) => `${f.name}:${f.status}:${f.extraction_status ?? ""}`)
    .join("|");

  useEffect(() => {
    const hasExtracting = files.some(
      (f) => f.status === "uploaded" && f.extraction_status && EXTRACTING_STATUSES.has(f.extraction_status)
    );
    if (!courseId || !hasExtracting) {
      if (extractionPollRef.current) clearTimeout(extractionPollRef.current);
      return;
    }

    const poll = async () => {
      try {
        const data = await getCourseResources(courseId);
        const byName: Record<string, string> = {};
        for (const f of data.files ?? []) {
          byName[f.name] = f.extraction_status ?? "done";
        }
        setFiles((prev) =>
          prev.map((f) => {
            const serverStatus = byName[f.name];
            if (serverStatus !== undefined && serverStatus !== f.extraction_status) {
              return { ...f, extraction_status: serverStatus as UploadedFile["extraction_status"] };
            }
            return f;
          })
        );
        const stillExtracting = (data.files ?? []).some((f) =>
          EXTRACTING_STATUSES.has(f.extraction_status ?? "done")
        );
        if (stillExtracting) {
          extractionPollRef.current = setTimeout(poll, 3000);
        } else {
          if (!isIndexing) {
            try {
              const status = await getIndexStatusApi(courseId);
              if (status.task && ["PENDING", "STARTED", "RETRY"].includes(status.task.state)) {
                setTaskId(status.task.id ?? null);
                setIsIndexing(true);
                lastIndexProgressTimeRef.current = Date.now();
              }
            } catch {
              // ignore
            }
          }
        }
      } catch {
        extractionPollRef.current = setTimeout(poll, 5000);
      }
    };

    extractionPollRef.current = setTimeout(poll, 2000);
    return () => {
      if (extractionPollRef.current) clearTimeout(extractionPollRef.current);
    };
    // extractionKey captures the meaningful shape of files for this effect;
    // files is intentionally referenced inside but not a dep to avoid churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, extractionKey, isIndexing]);

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

  // Fetch index-status on mount of the indexation/linker step when we don't
  // already have a value. Without this, an admin who opens an already-
  // generated course and clicks Suivant manually never populates indexStatus
  // (hydrate only fires for resumeCreationStep="indexing"|"indexed", and the
  // polling effect only runs while isIndexing=true). Result before this
  // effect: canGoNext stays false on the indexation step and the user is
  // stranded with Next disabled (#2051).
  useEffect(() => {
    if (!courseId) return;
    if (step !== "indexation" && step !== "linker") return;
    if (indexStatus) return;
    let cancelled = false;
    getIndexStatusApi(courseId)
      .then((s) => {
        if (!cancelled) setIndexStatus(buildIndexStatus(s));
      })
      .catch(() => {
        // Network failure — leave indexStatus null; the user can still
        // launch indexation explicitly via the step's primary button.
      });
    return () => {
      cancelled = true;
    };
  }, [step, courseId, indexStatus]);

  // Auto-advance linker → publish once the join has populated rows. Runs on
  // step change (manual Next from indexation), polling completion, resume,
  // and on relink success (#2044).
  useEffect(() => {
    if (step !== "linker") return;
    if (isLinkerComplete(indexStatus)) {
      const t = setTimeout(() => setStep("publish"), 800);
      return () => clearTimeout(t);
    }
  }, [step, indexStatus]);

  // Linker recovery — re-runs the chunk↔image join inline (no celery, no
  // re-embedding, no re-extraction). Powers the "Relancer le linker" button
  // on the dedicated linker step (#2044).
  const [isRelinking, setIsRelinking] = useState(false);
  const [relinkError, setRelinkError] = useState<string | null>(null);
  const relinkLinker = useCallback(async () => {
    if (!courseId) return;
    setIsRelinking(true);
    setRelinkError(null);
    try {
      await relinkImagesApi(courseId);
      const status = await getIndexStatusApi(courseId);
      setIndexStatus(buildIndexStatus(status));
    } catch {
      setRelinkError(tAi("linker.error"));
    } finally {
      setIsRelinking(false);
    }
  }, [courseId, tAi]);

  // ── Publish ───────────────────────────────────────────────────────

  useEffect(() => {
    if (step !== "publish" || !courseId || isIndexing) return;
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
  }, [step, courseId, isIndexing]);

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
    // Upload step gating is owned by the shared hook so both wizards behave
    // identically: at least one file present, none in error or in-flight.
    if (step === "upload") return upload.canAdvance;
    if (step === "objectives") return objectivesFr.trim().length > 0 || objectivesEn.trim().length > 0;
    if (step === "ai_proposal") return proposedTitle.fr.trim().length > 0 && proposedTitle.en.trim().length > 0;
    if (step === "generate") return generatedModules.length > 0;
    if (step === "syllabus_edit") return generatedModules.length > 0;
    if (step === "lesson_preview") return true; // Optional step — always skippable
    // Indexation step: text + image extraction must be done. The linker
    // gets its own step now (#2044) — don't block indexation on link rows.
    if (step === "indexation") return isExtractionComplete(indexStatus);
    // Linker step: chunk↔image join must have produced rows (or there were
    // no images to link). This is also the publish gate.
    if (step === "linker") return isLinkerComplete(indexStatus);
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

            {/* ── UPLOAD STEP — shared with CourseWizardClient ─────── */}
            {step === "upload" && (
              <CourseResourceUploadStep
                upload={upload}
                onRetry={() => {
                  if (courseId) void uploadAllPending(courseId);
                }}
              />
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
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                      <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4 shrink-0" />
                        {locale === "fr"
                          ? "Impossible de charger les catégories. Réessayez ou continuez sans."
                          : "Could not load categories. Retry or continue without."}
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 shrink-0"
                        onClick={() => loadTaxonomy()}
                      >
                        {locale === "fr" ? "Réessayer" : "Retry"}
                      </Button>
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

                {/* Visual syllabus editor */}
                {courseId && (
                  <SyllabusVisualEditor
                    courseId={courseId}
                    fetchOnMount
                  />
                )}
              </div>
            )}

            {/* ── INDEXATION STEP ───────────────────────────────────── */}
            {/* Promoted from inline-inside-syllabus_edit to a top-level
                step (#2041) so the Texte/Images/Liens recap is visible
                in the stepper instead of buried under "Modifier le
                programme". */}
            {step === "indexation" && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xl font-semibold">{t("index.title")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("index.description")}
                  </p>
                </div>

                {!isIndexing && !indexStatus?.indexed && (
                  <Button onClick={startIndexation} className="w-full min-h-11">
                    <Database className="mr-2 h-4 w-4" />
                    {t("index.button")}
                  </Button>
                )}

                {(isIndexing || indexStatus?.indexed) && (
                  <IndexationRecap
                    indexStatus={indexStatus}
                    isIndexing={isIndexing}
                    progressValue={progressValue}
                    onCancel={cancelIndexation}
                    t={t}
                  />
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
              </div>
            )}

            {/* ── LINKER STEP ───────────────────────────────────────── */}
            {/* Dedicated step for the chunk↔image linker (#2044). Splits
                the join phase out of indexation so admins can see when
                source_image_chunks rows weren't created and re-run the
                linker without re-embedding text or re-extracting images. */}
            {step === "linker" && (() => {
              const taskState = indexStatus?.task?.state;
              const linkingRunning = taskState === "LINKING_IMAGES";
              const images = indexStatus?.images_indexed ?? 0;
              const chunks = indexStatus?.chunks_indexed ?? 0;
              const links = indexStatus?.links_indexed ?? 0;
              const extractionDone = isExtractionComplete(indexStatus);
              const linksDone = isLinkerComplete(indexStatus);
              // The linker is inline-async, no celery task is required to
              // re-run it. As long as there is something to link (chunks
              // and/or images), surface the recovery action and treat the
              // current "no links yet" state as actionable rather than a
              // stuck "waiting" state (#2048).
              const hasLinkable = images > 0 || chunks > 0;
              const linksFailed = extractionDone && images > 0 && links === 0;

              let bannerCls = "border-muted bg-muted/30";
              let icon = (
                <div className="h-5 w-5 shrink-0 rounded-full border border-muted-foreground/40" />
              );
              let bannerText = tAi("linker.idle");
              if (linkingRunning || isRelinking) {
                bannerCls = "border-primary/30 bg-primary/5";
                icon = (
                  <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                );
                bannerText = tAi("linker.running");
              } else if (linksDone) {
                bannerCls = "border-green-300 bg-green-50 dark:border-green-700/40 dark:bg-green-950/30";
                icon = <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" />;
                bannerText = images === 0
                  ? tAi("linker.doneNone")
                  : tAi("linker.done");
              } else if (linksFailed) {
                bannerCls = "border-destructive/40 bg-destructive/5";
                icon = <AlertCircle className="h-5 w-5 shrink-0 text-destructive" />;
                bannerText = tAi("linker.failed");
              } else if (hasLinkable) {
                // Extraction has produced material to link but the celery
                // task isn't in a strict-final state (e.g. EXTRACTING_IMAGES
                // is still flagged on a stale poll). Don't show "waiting" —
                // the linker can be re-run any time (#2048).
                bannerText = tAi("linker.unknown");
              }

              return (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-xl font-semibold">{tAi("linker.title")}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {tAi("linker.description")}
                    </p>
                  </div>

                  <div className={`rounded-lg border p-4 space-y-3 ${bannerCls}`}>
                    <div className="flex items-start gap-3">
                      {icon}
                      <p className="text-sm font-medium">{bannerText}</p>
                    </div>

                    <div className="flex items-center justify-between gap-4 text-sm">
                      <span className="text-muted-foreground">
                        {t("index.recap.linksRow")}
                      </span>
                      <span className="font-medium">
                        {linksFailed
                          ? t("index.recap.linksFailed")
                          : links > 0
                          ? t("index.recap.linksCount", { count: links })
                          : linkingRunning || isRelinking
                          ? t("index.recap.linksPending")
                          : linksDone
                          ? t("index.recap.linksNone")
                          : "—"}
                      </span>
                    </div>

                    {images > 0 && (
                      <div className="flex items-center justify-between gap-4 text-xs text-muted-foreground">
                        <span>{t("index.recap.imagesRow")}</span>
                        <span>{t("index.recap.imagesCount", { count: images })}</span>
                      </div>
                    )}
                  </div>

                  {relinkError && (
                    <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {relinkError}
                    </div>
                  )}

                  {/* Relancer is gated only on "there is something to link"
                      and "the linker isn't currently running". The previous
                      `extractionDone` precondition stranded users when celery
                      task state was non-final (#2048). */}
                  {hasLinkable && !linkingRunning && (
                    <Button
                      onClick={relinkLinker}
                      disabled={isRelinking}
                      variant={linksFailed ? "default" : "outline"}
                      className="w-full min-h-11"
                    >
                      {isRelinking ? (
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" />
                      ) : (
                        <RotateCcw className="mr-2 h-4 w-4" />
                      )}
                      {tAi("linker.retryButton")}
                    </Button>
                  )}
                </div>
              );
            })()}

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
                    {!isFetchingPublishSummary && (publishSummaryIndexStatus?.chunks_indexed ?? 0) === 0 && (
                      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-3 text-sm text-amber-900 dark:border-amber-600/40 dark:bg-amber-950/30 dark:text-amber-200">
                        <div className="flex items-start gap-2">
                          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                          <p>{tAi("publish.ragMissing")}</p>
                        </div>
                        {isIndexing ? (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-700 border-t-transparent shrink-0" />
                              <p className="text-sm">
                                {taskProg ? getStepLabel(taskProg.step) : t("index.taskPending")}
                              </p>
                            </div>
                            <Progress value={progressValue} className="h-2" />
                          </div>
                        ) : (
                          <Button onClick={startIndexation} className="w-full min-h-11" variant="outline">
                            <Database className="mr-2 h-4 w-4" />
                            {t("index.button")}
                          </Button>
                        )}
                      </div>
                    )}
                    <Button
                      onClick={publishCourse}
                      className="w-full min-h-11"
                      disabled={
                        isPublishing ||
                        isIndexing ||
                        // Require the celery task to have hit COMPLETE — not
                        // just chunks_indexed > 0 — so we don't publish while
                        // image extraction is still in flight (#2032).
                        !isIndexationFullyComplete(publishSummaryIndexStatus)
                      }
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
