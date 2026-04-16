"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Upload, FileText, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { uploadQBankPdf, fetchQBankPdfJob } from "@/lib/api";
import type { QBankPdfJob } from "@/lib/api";

interface QBankPdfUploadProps {
  orgId: string;
  bankId: string;
  onComplete?: () => void;
}

export function QBankPdfUpload({ orgId, bankId, onComplete }: QBankPdfUploadProps) {
  const t = useTranslations("QBank");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<QBankPdfJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

  const startPolling = (jobId: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const updated = await fetchQBankPdfJob(orgId, bankId, jobId);
        setJob(updated);
        if (updated.status === "done") {
          stopPolling();
          onComplete?.();
        } else if (updated.status === "failed") {
          stopPolling();
          setError(updated.error_message ?? t("extractionFailed"));
        }
      } catch {
        stopPolling();
        setError(t("pollingError"));
      }
    }, 3000);
  };

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError(t("pdfOnly"));
        return;
      }
      setError(null);
      setUploading(true);
      setJob(null);
      try {
        const newJob = await uploadQBankPdf(orgId, bankId, file);
        setJob(newJob);
        if (newJob.status !== "done" && newJob.status !== "failed") {
          startPolling(newJob.job_id);
        } else if (newJob.status === "done") {
          onComplete?.();
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : t("uploadError"));
      } finally {
        setUploading(false);
      }
    },
    [orgId, bankId, onComplete, t]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  const isProcessing =
    job?.status === "pending" || job?.status === "processing";
  const isDone = job?.status === "done";
  const isFailed = job?.status === "failed";

  const progressPct =
    job && job.total_slides > 0
      ? Math.round((job.processed_slides / job.total_slides) * 100)
      : 0;

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && !isProcessing && inputRef.current?.click()}
        className={`flex min-h-36 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-4 py-8 transition-colors ${
          dragging
            ? "border-teal-500 bg-teal-50"
            : "border-stone-300 bg-stone-50 hover:border-teal-400 hover:bg-teal-50"
        } ${uploading || isProcessing ? "pointer-events-none opacity-60" : ""}`}
        role="button"
        aria-label={t("uploadDropzone")}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
      >
        {uploading ? (
          <Loader2 className="h-10 w-10 animate-spin text-teal-600" />
        ) : (
          <Upload className="h-10 w-10 text-stone-400" />
        )}
        <div className="text-center">
          <p className="text-sm font-medium text-stone-700">
            {uploading ? t("uploading") : t("dropOrClick")}
          </p>
          <p className="mt-1 text-xs text-stone-500">{t("pdfOnly")}</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="sr-only"
          onChange={handleChange}
          aria-hidden
        />
      </div>

      {isProcessing && job && (
        <div className="rounded-lg border bg-white p-4 space-y-3">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-teal-600 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-stone-700">
                {t("processingSlides", {
                  processed: job.processed_slides,
                  total: job.total_slides || "?",
                })}
              </p>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-stone-200">
                <div
                  className="h-full rounded-full bg-teal-500 transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
            <span className="text-xs font-semibold text-teal-700 shrink-0">
              {progressPct}%
            </span>
          </div>
        </div>
      )}

      {isDone && (
        <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 p-4">
          <CheckCircle className="h-5 w-5 text-green-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-green-800">{t("extractionDone")}</p>
            <p className="text-xs text-green-700">
              {t("slidesProcessed", { count: job?.processed_slides ?? 0 })}
            </p>
          </div>
        </div>
      )}

      {(isFailed || error) && (
        <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <XCircle className="h-5 w-5 text-red-600 shrink-0" />
          <p className="text-sm text-red-700">{error ?? job?.error_message}</p>
        </div>
      )}

      {job && !isProcessing && !isDone && !isFailed && (
        <div className="flex items-center gap-3 rounded-lg border bg-stone-50 p-4">
          <FileText className="h-5 w-5 text-stone-400 shrink-0" />
          <p className="text-sm text-stone-600">{t("jobPending")}</p>
        </div>
      )}
    </div>
  );
}
