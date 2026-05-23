"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Download, Loader2, Package, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  type BundleListItem,
  deleteBundle,
  downloadBundle,
  listBundles,
} from "@/lib/api-bundles";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export function BundlesClient() {
  const t = useTranslations("Admin.bundles");

  const [bundles, setBundles] = useState<BundleListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevStatusRef = useRef<Record<string, string>>({});

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  }

  const load = useCallback(async () => {
    try {
      const data = await listBundles({ limit: 100 });
      const prev = prevStatusRef.current;
      for (const b of data) {
        const was = prev[b.bundle_id];
        if (was && was !== b.status) {
          if (b.status === "ready") showToast(t("toastReady"));
          if (b.status === "failed") showToast(t("toastFailed"));
        }
      }
      prevStatusRef.current = Object.fromEntries(
        data.map((b) => [b.bundle_id, b.status]),
      );
      setBundles(data);
      setError(null);
    } catch {
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const hasActive = bundles.some(
      (b) => b.status === "generating" || b.status === "pending",
    );
    if (!hasActive) {
      if (pollRef.current) clearTimeout(pollRef.current);
      return;
    }
    pollRef.current = setTimeout(load, 3000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [bundles, load]);

  async function handleDownload(b: BundleListItem) {
    setDownloading(b.bundle_id);
    try {
      const filename = `${b.course_title}_${b.language}.zip`.replace(
        /[^a-zA-Z0-9_.-]/g,
        "_",
      );
      await downloadBundle(b.bundle_id, filename);
    } catch {
      showToast(t("error"));
    } finally {
      setDownloading(null);
    }
  }

  async function handleDelete(bundleId: string) {
    setDeleting(bundleId);
    try {
      await deleteBundle(bundleId);
      await load();
    } catch {
      showToast(t("error"));
    } finally {
      setDeleting(null);
      setConfirmDelete(null);
    }
  }

  function statusBadge(bundleStatus: string) {
    const label = t(`status.${bundleStatus}` as Parameters<typeof t>[0]);
    const cls: Record<string, string> = {
      pending: "bg-muted text-muted-foreground",
      generating:
        "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
      ready:
        "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
      failed:
        "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    };
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${cls[bundleStatus] ?? cls.pending}`}
      >
        {bundleStatus === "generating" && (
          <Loader2 className="size-3 animate-spin" />
        )}
        {label}
      </span>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" />
        {t("loading")}
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-auto p-4">
      {toast && (
        <div className="fixed right-4 top-4 z-50 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground shadow-lg">
          {toast}
        </div>
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-lg bg-background p-6 shadow-xl">
            <p className="text-sm">{t("deleteConfirm")}</p>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setConfirmDelete(null)}
                disabled={!!deleting}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(confirmDelete)}
                disabled={!!deleting}
              >
                {deleting === confirmDelete ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  t("delete")
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {bundles.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-muted-foreground">
          <Package className="size-10 opacity-40" />
          <p className="text-sm">{t("empty")}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50 text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left">{t("table.course")}</th>
                <th className="px-4 py-3 text-left">
                  {t("table.language")}
                </th>
                <th className="px-4 py-3 text-left">{t("table.level")}</th>
                <th className="px-4 py-3 text-left">{t("table.status")}</th>
                <th className="px-4 py-3 text-left">{t("table.size")}</th>
                <th className="px-4 py-3 text-left">{t("table.created")}</th>
                <th className="px-4 py-3 text-right">
                  {t("table.actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {bundles.map((b) => (
                <tr key={b.bundle_id} className="hover:bg-muted/30">
                  <td className="px-4 py-3 font-medium">
                    {b.course_title}
                    {b.error_message && b.status === "failed" && (
                      <p className="mt-0.5 max-w-[200px] truncate text-xs text-destructive/80">
                        {b.error_message}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 uppercase">{b.language}</td>
                  <td className="px-4 py-3">{b.level}</td>
                  <td className="px-4 py-3">{statusBadge(b.status)}</td>
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">
                    {b.file_count != null && (
                      <span className="mr-1 text-xs">{b.file_count}f</span>
                    )}
                    {formatBytes(b.file_size_bytes)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDate(b.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={b.status !== "ready" || !!downloading}
                        onClick={() => handleDownload(b)}
                        title={t("download")}
                      >
                        {downloading === b.bundle_id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Download className="size-4" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!!deleting}
                        onClick={() => setConfirmDelete(b.bundle_id)}
                        title={t("delete")}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
