"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Trash2,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  uploadCourseResource,
  deleteCourseResource,
  getCourseResources,
  type UploadedFile,
} from "@/lib/api-course-admin";

const EXTRACTING_STATUSES = new Set<string>(["pending", "extracting"]);

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ── Hook ─────────────────────────────────────────────────────────────────────
//
// Owns the entire upload state machine: queued → uploading → uploaded | error.
// Both wizards (AICourseWizard and CourseWizardClient) consume this so the
// upload behaviour and gating live in exactly one place.

export interface UseCourseResourceUploadOptions {
  /** Existing courseId (when resuming) or null (first-time creation). */
  courseId: string | null;
  /** Fetch already-uploaded files from the backend on mount. */
  loadExistingOnMount?: boolean;
}

export interface UseCourseResourceUploadResult {
  files: UploadedFile[];
  setFiles: React.Dispatch<React.SetStateAction<UploadedFile[]>>;
  pendingFiles: File[];
  uploadError: string | null;
  setUploadError: (msg: string | null) => void;
  isFetchingExistingFiles: boolean;
  isDragOver: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleFiles: (incoming: File[]) => Promise<void>;
  removeFile: (name: string) => Promise<void>;
  /**
   * Push every locally-queued file to the backend at the given courseId.
   * Per file: marks "uploading", awaits the POST, then sets "uploaded" or
   * "error" based on the actual result. Returns ok=false if any file failed.
   * Callers MUST gate step advancement on the returned `ok`.
   */
  uploadAllPending: (
    targetCourseId: string,
  ) => Promise<{ ok: boolean; failed: string[] }>;
  /**
   * Whether the wizard's "Suivant" can advance from the upload step:
   * at least one file present, none in "error" or in-flight "uploading".
   */
  canAdvance: boolean;
  /** Drag handlers for the dropzone div. */
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  /** Handler for the hidden file input. */
  onFileInput: (e: React.ChangeEvent<HTMLInputElement>) => void;
  /** Click the hidden input (open native file picker). */
  openFilePicker: () => void;
}

export function useCourseResourceUpload(
  options: UseCourseResourceUploadOptions,
): UseCourseResourceUploadResult {
  const { courseId, loadExistingOnMount = true } = options;
  const t = useTranslations("AdminCourses.wizard");

  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isFetchingExistingFiles, setIsFetchingExistingFiles] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Hydrate already-uploaded files when the wizard resumes against an existing course.
  useEffect(() => {
    if (!loadExistingOnMount || !courseId) return;
    let cancelled = false;
    (async () => {
      setIsFetchingExistingFiles(true);
      try {
        const data = await getCourseResources(courseId);
        if (cancelled) return;
        const serverFiles: UploadedFile[] = (data.files ?? []).map((f) => ({
          name: f.name,
          size_bytes: f.size_bytes,
          status: "uploaded" as const,
          extraction_status: f.extraction_status,
        }));
        setFiles((prev) => {
          const localNames = new Set(prev.map((f) => f.name));
          return [...prev, ...serverFiles.filter((f) => !localNames.has(f.name))];
        });
      } catch {
        // Silent — the wizard will still let the user upload fresh files.
      } finally {
        if (!cancelled) setIsFetchingExistingFiles(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [courseId, loadExistingOnMount]);

  const uploadOne = useCallback(
    async (targetCourseId: string, file: File): Promise<boolean> => {
      setFiles((prev) =>
        prev.map((f) =>
          f.name === file.name ? { ...f, status: "uploading" as const } : f,
        ),
      );
      const result = await uploadCourseResource(targetCourseId, file);
      if (!result.ok) {
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name
              ? {
                  ...f,
                  status: "error" as const,
                  error: result.error || t("upload.uploadError"),
                }
              : f,
          ),
        );
        return false;
      }
      setFiles((prev) =>
        prev.map((f) =>
          f.name === file.name
            ? { ...f, status: "uploaded" as const, extraction_status: "pending" as const }
            : f,
        ),
      );
      return true;
    },
    [t],
  );

  const handleFiles = useCallback(
    async (incoming: File[]) => {
      const pdfs = incoming.filter((f) => f.type === "application/pdf");
      if (!pdfs.length) return;

      // No-courseId: queue files locally; the parent wizard will create the
      // course and call uploadAllPending(). Files stay "queued" — never shown
      // as "uploaded" until the backend confirms.
      // With courseId: upload immediately so failures surface inline.
      const newEntries: UploadedFile[] = pdfs
        .filter((f) => !files.some((existing) => existing.name === f.name))
        .map((f) => ({
          name: f.name,
          size_bytes: f.size,
          status: courseId ? ("uploading" as const) : ("queued" as const),
        }));
      if (!newEntries.length) return;

      setFiles((prev) => [...prev, ...newEntries]);
      setUploadError(null);

      if (courseId) {
        for (const file of pdfs) {
          await uploadOne(courseId, file);
        }
      } else {
        setPendingFiles((prev) => [...prev, ...pdfs]);
      }
    },
    [courseId, files, uploadOne],
  );

  const removeFile = useCallback(
    async (name: string) => {
      if (courseId) {
        await deleteCourseResource(courseId, name);
      }
      setFiles((prev) => prev.filter((f) => f.name !== name));
      setPendingFiles((prev) => prev.filter((f) => f.name !== name));
      // Removing a file that was the only error source clears the banner.
      setUploadError((prev) => {
        if (!prev) return prev;
        const stillHasError = files.some((f) => f.name !== name && f.status === "error");
        return stillHasError ? prev : null;
      });
    },
    [courseId, files],
  );

  const uploadAllPending = useCallback(
    async (
      targetCourseId: string,
    ): Promise<{ ok: boolean; failed: string[] }> => {
      setUploadError(null);
      const queue = [...pendingFiles];
      if (queue.length === 0) return { ok: true, failed: [] };

      // Per-file: try the upload, track which succeeded vs failed. Only
      // successful files are pulled out of pendingFiles — failed ones stay
      // queued so the next click of Réessayer actually re-uploads them
      // instead of short-circuiting on an empty queue (#2026).
      const succeeded: string[] = [];
      const failed: string[] = [];
      for (const file of queue) {
        const ok = await uploadOne(targetCourseId, file);
        if (ok) succeeded.push(file.name);
        else failed.push(file.name);
      }
      setPendingFiles((prev) => prev.filter((f) => !succeeded.includes(f.name)));

      if (failed.length > 0) {
        setUploadError(
          t("upload.someFilesFailed", { names: failed.join(", ") }),
        );
        return { ok: false, failed };
      }
      return { ok: true, failed: [] };
    },
    [pendingFiles, t, uploadOne],
  );

  const canAdvance =
    files.length > 0 &&
    !files.some((f) => f.status === "error" || f.status === "uploading") &&
    files.some((f) => f.status === "uploaded" || f.status === "queued");

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);
  const onDragLeave = useCallback(() => setIsDragOver(false), []);
  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFiles(Array.from(e.dataTransfer.files));
    },
    [handleFiles],
  );
  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      handleFiles(Array.from(e.target.files || []));
      e.target.value = "";
    },
    [handleFiles],
  );
  const openFilePicker = useCallback(() => fileInputRef.current?.click(), []);

  return {
    files,
    setFiles,
    pendingFiles,
    uploadError,
    setUploadError,
    isFetchingExistingFiles,
    isDragOver,
    fileInputRef,
    handleFiles,
    removeFile,
    uploadAllPending,
    canAdvance,
    onDragOver,
    onDragLeave,
    onDrop,
    onFileInput,
    openFilePicker,
  };
}

// ── Presentational component ────────────────────────────────────────────────
//
// Renders the full upload step body: header, dropzone, file list with status
// icons, aggregate error banner. Both wizards drop this in directly.

export interface CourseResourceUploadStepProps {
  upload: UseCourseResourceUploadResult;
  /** Optional retry handler (the parent must know which courseId to upload into). */
  onRetry?: () => void;
}

export function CourseResourceUploadStep({
  upload,
  onRetry,
}: CourseResourceUploadStepProps) {
  const t = useTranslations("AdminCourses.wizard");
  const {
    files,
    uploadError,
    isFetchingExistingFiles,
    isDragOver,
    fileInputRef,
    onDragOver,
    onDragLeave,
    onDrop,
    onFileInput,
    openFilePicker,
    removeFile,
  } = upload;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-xl font-semibold">{t("upload.title")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("upload.description")}
        </p>
      </div>

      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={openFilePicker}
        onKeyDown={(e) => e.key === "Enter" && openFilePicker()}
        role="button"
        tabIndex={0}
        aria-label={t("upload.dropzone")}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
          isDragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-muted/50"
        }`}
      >
        <Upload className="mb-3 h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-medium">
          {isDragOver ? t("upload.dropzoneActive") : t("upload.dropzone")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("upload.fileTypes")}
        </p>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={onFileInput}
      />

      {uploadError && (
        <div className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
          <div className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{uploadError}</span>
          </div>
          {onRetry && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              className="self-start min-h-[44px]"
            >
              <Upload className="mr-2 h-4 w-4" />
              {t("upload.retry")}
            </Button>
          )}
        </div>
      )}

      {isFetchingExistingFiles && (
        <div className="flex items-center justify-center py-4">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}

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
                <p className="text-xs text-muted-foreground">
                  {formatBytes(f.size_bytes)}
                </p>
              </div>

              {f.status === "queued" && (
                <span
                  title={t("upload.queued")}
                  className="text-xs text-muted-foreground"
                >
                  {t("upload.queued")}
                </span>
              )}
              {f.status === "uploading" && (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              )}
              {f.status === "uploaded" &&
                f.extraction_status &&
                EXTRACTING_STATUSES.has(f.extraction_status) && (
                  <span
                    title={t("upload.extracting")}
                    className="flex items-center gap-1 text-xs text-muted-foreground"
                  >
                    <div className="h-3 w-3 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
                    {t("upload.extracting")}
                  </span>
                )}
              {f.status === "uploaded" &&
                (!f.extraction_status || f.extraction_status === "done") && (
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                )}
              {f.status === "uploaded" && f.extraction_status === "failed" && (
                <span title={t("upload.extractionFailed")}>
                  <AlertCircle className="h-4 w-4 text-destructive" />
                </span>
              )}
              {f.status === "error" && (
                <span title={f.error}>
                  <AlertCircle className="h-4 w-4 text-destructive" />
                </span>
              )}

              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  removeFile(f.name);
                }}
                aria-label={t("upload.remove")}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
