"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authClient } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SourceStats {
  source: string;
  chunk_count: number;
  token_count: number;
  last_indexed: string | null;
}

interface RagStatus {
  total_chunks: number;
  total_tokens: number;
  sources: SourceStats[];
}

interface JobRecord {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  updated_at: number;
  source?: string;
  chunks_indexed?: number;
  total_chunks?: number;
  error?: string;
}

interface JobsResponse {
  jobs: JobRecord[];
}

async function fetchWithAuth<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authClient.authenticatedFetch<T>(path, init);
  return res;
}

function statusColor(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "completed") return "default";
  if (status === "running" || status === "pending") return "secondary";
  if (status === "failed") return "destructive";
  return "outline";
}

function useRagStatus() {
  return useQuery<RagStatus>({
    queryKey: ["admin", "rag", "status"],
    queryFn: () => fetchWithAuth<RagStatus>("/api/v1/admin/rag/status"),
    refetchInterval: 30_000,
  });
}

function useRagJobs() {
  return useQuery<JobsResponse>({
    queryKey: ["admin", "rag", "jobs"],
    queryFn: () => fetchWithAuth<JobsResponse>("/api/v1/admin/rag/jobs"),
    refetchInterval: 5_000,
  });
}

export function RagIndexClient() {
  const t = useTranslations("Admin.RagIndex");
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadSourceId, setUploadSourceId] = useState("");
  const [uploadProgress, setUploadProgress] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  const { data: status, isLoading: statusLoading, error: statusError } = useRagStatus();
  const { data: jobsData, isLoading: jobsLoading } = useRagJobs();

  const reindexMutation = useMutation({
    mutationFn: (sourceId?: string) =>
      fetchWithAuth<{ job_id: string; status: string; message: string }>(
        "/api/v1/admin/rag/reindex",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: sourceId ?? null }),
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "rag", "jobs"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (sourceId: string) =>
      fetchWithAuth<{ chunks_removed: number; message: string }>(
        `/api/v1/admin/rag/source/${sourceId}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "rag", "status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "rag", "jobs"] });
    },
  });

  const handleUpload = useCallback(async () => {
    const file = fileRef.current?.files?.[0];
    if (!file || !uploadSourceId.trim()) return;

    setUploadError(null);
    setUploadSuccess(null);
    setUploadProgress(true);

    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(
        `${API_BASE}/api/v1/admin/rag/upload?source_id=${encodeURIComponent(uploadSourceId)}`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: t("uploadFailed") }));
        throw new Error(err.detail || t("uploadFailed"));
      }

      const data = await res.json();
      setUploadSuccess(t("uploadQueued", { jobId: data.job_id }));
      if (fileRef.current) fileRef.current.value = "";
      setUploadSourceId("");
      queryClient.invalidateQueries({ queryKey: ["admin", "rag", "jobs"] });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : t("uploadFailed"));
    } finally {
      setUploadProgress(false);
    }
  }, [uploadSourceId, queryClient, t]);

  return (
    <div className="space-y-6">
      {/* Index Health Dashboard */}
      <Card>
        <CardHeader>
          <CardTitle>{t("indexHealth")}</CardTitle>
          <CardDescription>{t("indexHealthDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {statusLoading && (
            <div className="space-y-2">
              <div className="h-4 w-48 animate-pulse rounded bg-muted" />
              <div className="h-4 w-32 animate-pulse rounded bg-muted" />
            </div>
          )}
          {statusError && (
            <p className="text-sm text-destructive">{t("loadError")}</p>
          )}
          {status && (
            <div className="space-y-4">
              <div className="flex gap-8">
                <div>
                  <p className="text-sm text-muted-foreground">{t("totalChunks")}</p>
                  <p className="text-2xl font-bold">{status.total_chunks.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t("totalTokens")}</p>
                  <p className="text-2xl font-bold">{status.total_tokens.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t("sources")}</p>
                  <p className="text-2xl font-bold">{status.sources.length}</p>
                </div>
              </div>

              <div className="space-y-3">
                {status.sources.map((src) => (
                  <div
                    key={src.source}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{src.source}</p>
                      <p className="text-sm text-muted-foreground">
                        {t("chunkCount", { count: src.chunk_count })}
                        {src.last_indexed && (
                          <span className="ml-2">
                            · {t("lastIndexed")}{" "}
                            {new Intl.DateTimeFormat(undefined, {
                              dateStyle: "medium",
                              timeStyle: "short",
                            }).format(new Date(src.last_indexed))}
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={reindexMutation.isPending}
                        onClick={() => reindexMutation.mutate(src.source)}
                        className="min-h-9"
                      >
                        {t("reindexSource")}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={deleteMutation.isPending}
                        onClick={() => {
                          if (window.confirm(t("confirmDelete", { source: src.source }))) {
                            deleteMutation.mutate(src.source);
                          }
                        }}
                        className="min-h-9"
                      >
                        {t("deleteSource")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <Button
                className="w-full min-h-11"
                disabled={reindexMutation.isPending}
                onClick={() => reindexMutation.mutate(undefined)}
              >
                {reindexMutation.isPending ? t("reindexing") : t("reindexAll")}
              </Button>

              {reindexMutation.isSuccess && (
                <p className="text-sm text-green-600 dark:text-green-400">
                  {t("reindexQueued", { jobId: reindexMutation.data.job_id })}
                </p>
              )}
              {reindexMutation.isError && (
                <p className="text-sm text-destructive">{t("reindexFailed")}</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* PDF Upload */}
      <Card>
        <CardHeader>
          <CardTitle>{t("uploadPdf")}</CardTitle>
          <CardDescription>{t("uploadPdfDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="source-id-input">
                {t("sourceId")}
              </label>
              <Input
                id="source-id-input"
                placeholder={t("sourceIdPlaceholder")}
                value={uploadSourceId}
                onChange={(e) => setUploadSourceId(e.target.value)}
                className="max-w-sm"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="pdf-file-input">
                {t("pdfFile")}
              </label>
              <Input
                id="pdf-file-input"
                type="file"
                accept=".pdf"
                ref={fileRef}
                className="max-w-sm"
              />
            </div>
            {uploadProgress && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">{t("uploading")}</p>
                <Progress value={null} className="h-2" />
              </div>
            )}
            {uploadSuccess && (
              <p className="text-sm text-green-600 dark:text-green-400">{uploadSuccess}</p>
            )}
            {uploadError && (
              <p className="text-sm text-destructive">{uploadError}</p>
            )}
            <Button
              className="min-h-11"
              disabled={uploadProgress || !uploadSourceId.trim()}
              onClick={handleUpload}
            >
              {uploadProgress ? t("uploading") : t("uploadAndIndex")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Job History */}
      <Card>
        <CardHeader>
          <CardTitle>{t("jobHistory")}</CardTitle>
          <CardDescription>{t("jobHistoryDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {jobsLoading && (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 animate-pulse rounded bg-muted" />
              ))}
            </div>
          )}
          {!jobsLoading && (!jobsData?.jobs || jobsData.jobs.length === 0) && (
            <p className="text-sm text-muted-foreground">{t("noJobs")}</p>
          )}
          {jobsData?.jobs && jobsData.jobs.length > 0 && (
            <div className="space-y-2">
              {jobsData.jobs.map((job) => (
                <div
                  key={job.job_id}
                  className="flex items-start justify-between gap-4 rounded-lg border p-3 text-sm"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={statusColor(job.status)}>{job.status}</Badge>
                      {job.source && (
                        <span className="text-muted-foreground">{job.source}</span>
                      )}
                    </div>
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      {t("jobId")}: {job.job_id}
                    </p>
                    {job.chunks_indexed !== undefined && (
                      <p className="text-muted-foreground">
                        {t("chunksIndexed", { count: job.chunks_indexed })}
                      </p>
                    )}
                    {job.total_chunks !== undefined && (
                      <p className="text-muted-foreground">
                        {t("totalChunksIndexed", { count: job.total_chunks })}
                      </p>
                    )}
                    {job.error && (
                      <p className="text-destructive">{t("error")}: {job.error}</p>
                    )}
                  </div>
                  <p className="shrink-0 text-xs text-muted-foreground">
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: "short",
                      timeStyle: "short",
                    }).format(new Date(job.updated_at * 1000))}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
