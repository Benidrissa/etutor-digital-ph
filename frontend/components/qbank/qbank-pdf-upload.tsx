"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileText, Loader2, Upload } from "lucide-react";
import {
  getQBankProcessingStatus,
  uploadQBankPdf,
  type QBankProcessingStatus,
} from "@/lib/api";

interface Props {
  bankId: string;
  onProcessed?: (result: QBankProcessingStatus) => void;
}

type Phase = "idle" | "uploading" | "processing" | "done" | "error";

const POLL_INTERVAL_MS = 3000;

export function QBankPdfUpload({ bankId, onProcessed }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<QBankProcessingStatus | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleFile = useCallback(
    async (file: File) => {
      if (file.type !== "application/pdf") {
        setPhase("error");
        setMessage("Only PDF files are accepted.");
        return;
      }
      setPhase("uploading");
      setMessage(null);
      setFilename(file.name);
      try {
        const res = await uploadQBankPdf(bankId, file);
        setTaskId(res.task_id);
        setPhase("processing");
      } catch (err: unknown) {
        setPhase("error");
        setMessage(err instanceof Error ? err.message : "Upload failed");
      }
    },
    [bankId]
  );

  useEffect(() => {
    if (phase !== "processing" || !taskId) return;
    let cancelled = false;

    async function poll() {
      try {
        const s = await getQBankProcessingStatus(bankId, taskId!);
        if (cancelled) return;
        setStatus(s);
        if (["success", "failure"].includes(s.status)) {
          setPhase(s.status === "success" ? "done" : "error");
          if (s.status === "failure") setMessage(s.error ?? "Processing failed");
          onProcessed?.(s);
          return;
        }
      } catch (err: unknown) {
        if (cancelled) return;
        setPhase("error");
        setMessage(err instanceof Error ? err.message : "Polling failed");
        return;
      }
      if (!cancelled) setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [bankId, phase, taskId, onProcessed]);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) void handleFile(file);
    },
    [handleFile]
  );

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition ${
          dragActive ? "border-green-500 bg-green-50" : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <Upload className="mb-2 h-8 w-8 text-gray-400" />
        <p className="text-sm font-medium">Drop a PDF here or click to select</p>
        <p className="text-xs text-muted-foreground">
          Slides with an image + question + options per page
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            e.target.value = "";
          }}
        />
      </div>

      {filename && (
        <div className="flex items-center gap-2 rounded-md border bg-white px-3 py-2 text-sm">
          <FileText className="h-4 w-4 text-gray-400" />
          <span className="flex-1 truncate">{filename}</span>
          {phase === "uploading" && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
          {phase === "processing" && (
            <span className="flex items-center gap-1 text-xs text-blue-600">
              <Loader2 className="h-3 w-3 animate-spin" /> Extracting…
            </span>
          )}
          {phase === "done" && <CheckCircle2 className="h-4 w-4 text-green-600" />}
          {phase === "error" && <AlertCircle className="h-4 w-4 text-red-600" />}
        </div>
      )}

      {phase === "done" && status?.result && (
        <p className="text-sm text-green-700">
          Extracted {status.result.questions_created} question(s)
          {Array.isArray(status.result.errors) && status.result.errors.length > 0
            ? ` with ${status.result.errors.length} warning(s)`
            : ""}
          .
        </p>
      )}

      {message && phase === "error" && (
        <p className="text-sm text-red-700">{message}</p>
      )}
    </div>
  );
}
