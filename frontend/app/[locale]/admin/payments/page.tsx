"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch, API_BASE } from "@/lib/api";
import { authClient } from "@/lib/auth";
import { Download, ChevronLeft, ChevronRight, X } from "lucide-react";

interface DeviceStatus {
  device_id: string;
  battery: number | null;
  charging: boolean | null;
  signal: number | null;
  pending: number | null;
  failed: number | null;
  last_sms_at: string | null;
  last_heartbeat_at: string;
  app_version: string | null;
  is_stale: boolean;
}

interface RelayStatus {
  devices: DeviceStatus[];
  recent_sms_count: number;
  failed_parse_count: number;
}

interface SmsRecord {
  id: string;
  sms_id: string;
  device_id: string;
  sender: string;
  body: string;
  sms_received_at: string;
  processing_status: string;
  parsed_amount: number | null;
  parsed_phone: string | null;
  parsed_reference: string | null;
  parsed_provider: string | null;
  error_message: string | null;
  created_at: string;
}

interface SmsListResponse {
  items: SmsRecord[];
  total: number;
  offset: number;
  limit: number;
}

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  payment_processed: "default",
  parsed: "secondary",
  parse_failed: "destructive",
  pending: "outline",
  duplicate: "outline",
  ignored: "outline",
};

const FILTERS = [
  { value: "", key: "allStatuses" },
  { value: "payment_processed", key: "processed" },
  { value: "parse_failed", key: "parseFailed" },
  { value: "pending", key: "pending" },
] as const;

const PAGE_SIZE = 50;

function signalBars(signal: number | null): string {
  if (signal == null) return "—";
  const clamped = Math.max(0, Math.min(signal, 4));
  return "▪".repeat(clamped) + "▫".repeat(4 - clamped);
}

function statusLabel(
  statuses: Record<string, string> | null,
  key: string
): string {
  return statuses?.[key] ?? key;
}

export default function PaymentsPage() {
  const t = useTranslations("Admin.payments");
  const locale = useLocale();

  const [relayStatus, setRelayStatus] = useState<RelayStatus | null>(null);
  const [smsRecords, setSmsRecords] = useState<SmsRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState("");
  const [phoneSearch, setPhoneSearch] = useState("");
  const [referenceSearch, setReferenceSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);

  // Pre-fetch statuses map once to avoid t.raw() in render loop
  let statusesMap: Record<string, string> | null = null;
  try {
    const raw = t.raw("statuses");
    if (raw && typeof raw === "object") {
      statusesMap = raw as Record<string, string>;
    }
  } catch {
    statusesMap = null;
  }

  const buildQueryString = useCallback(
    (currentOffset: number) => {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status_filter", statusFilter);
      if (phoneSearch.trim()) params.set("phone", phoneSearch.trim());
      if (referenceSearch.trim())
        params.set("reference", referenceSearch.trim());
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      params.set("offset", String(currentOffset));
      params.set("limit", String(PAGE_SIZE));
      return params.toString();
    },
    [statusFilter, phoneSearch, referenceSearch, dateFrom, dateTo]
  );

  const fetchData = useCallback(
    async (currentOffset: number) => {
      setLoading(true);
      setError(false);
      try {
        const qs = buildQueryString(currentOffset);
        const [status, smsResponse] = await Promise.all([
          apiFetch<RelayStatus>("/api/v1/admin/relay/status"),
          apiFetch<SmsListResponse>(`/api/v1/admin/relay/sms?${qs}`),
        ]);
        setRelayStatus(status);
        setSmsRecords(smsResponse.items);
        setTotal(smsResponse.total);
      } catch {
        setRelayStatus(null);
        setSmsRecords([]);
        setTotal(0);
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [buildQueryString]
  );

  useEffect(() => {
    fetchData(offset);
  }, [offset, fetchData]);

  // Reset to page 0 when filters change
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, phoneSearch, referenceSearch, dateFrom, dateTo]);

  const handleExportCsv = async () => {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status_filter", statusFilter);
    if (phoneSearch.trim()) params.set("phone", phoneSearch.trim());
    if (referenceSearch.trim())
      params.set("reference", referenceSearch.trim());
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);

    try {
      const token = await authClient.getValidToken();
      const res = await fetch(
        `${API_BASE}/api/v1/admin/relay/sms/export/csv?${params.toString()}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sms_export.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silently fail
    }
  };

  const hasFilters =
    statusFilter || phoneSearch || referenceSearch || dateFrom || dateTo;

  const clearFilters = () => {
    setStatusFilter("");
    setPhoneSearch("");
    setReferenceSearch("");
    setDateFrom("");
    setDateTo("");
    setOffset(0);
  };

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showFrom = total === 0 ? 0 : offset + 1;
  const showTo = Math.min(offset + PAGE_SIZE, total);

  if (loading && offset === 0 && !hasFilters) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-6">
        <h1 className="text-2xl font-bold mb-1">{t("title")}</h1>
        <div className="flex min-h-[40vh] items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </div>
    );
  }

  if (error && !hasFilters) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-6">
        <h1 className="text-2xl font-bold mb-1">{t("title")}</h1>
        <p className="py-8 text-center text-destructive">{t("error")}</p>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("devices")}</p>
            <p className="text-3xl font-bold">
              {relayStatus?.devices.length ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("processed")}</p>
            <p className="text-3xl font-bold text-green-600">
              {relayStatus?.recent_sms_count ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("parseFailed")}</p>
            <p className="text-3xl font-bold text-red-600">
              {relayStatus?.failed_parse_count ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Devices table */}
      {relayStatus && relayStatus.devices.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("devices")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 pr-4">{t("deviceId")}</th>
                    <th className="pb-2 pr-4">{t("battery")}</th>
                    <th className="pb-2 pr-4">{t("signal")}</th>
                    <th className="pb-2 pr-4">{t("lastSeen")}</th>
                    <th className="pb-2">{t("status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {relayStatus.devices.map((d) => (
                    <tr key={d.device_id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-mono text-xs">
                        {d.device_id}
                      </td>
                      <td className="py-2 pr-4">
                        {d.battery != null ? `${d.battery}%` : "—"}
                        {d.charging && " ⚡"}
                      </td>
                      <td className="py-2 pr-4">{signalBars(d.signal)}</td>
                      <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
                        {new Date(d.last_heartbeat_at).toLocaleDateString(
                          locale,
                          {
                            day: "2-digit",
                            month: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          }
                        )}
                      </td>
                      <td className="py-2">
                        <Badge
                          variant={d.is_stale ? "destructive" : "default"}
                        >
                          {d.is_stale ? t("offline") : t("online")}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* SMS records */}
      <Card>
        <CardHeader className="pb-2 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <CardTitle className="text-base">{t("smsRecords")}</CardTitle>
            <div className="flex items-center gap-2">
              <div className="flex gap-1 bg-muted rounded-lg p-1">
                {FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => setStatusFilter(f.value)}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                      statusFilter === f.value
                        ? "bg-background text-foreground shadow-sm font-medium"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {t(f.key)}
                  </button>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportCsv}
                className="gap-1.5"
              >
                <Download className="h-4 w-4" />
                <span className="hidden sm:inline">{t("exportCsv")}</span>
              </Button>
            </div>
          </div>

          {/* Filter inputs */}
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              placeholder={t("searchPhone")}
              value={phoneSearch}
              onChange={(e) => setPhoneSearch(e.target.value)}
              className="flex-1 rounded-md border border-stone-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <input
              type="text"
              placeholder={t("searchReference")}
              value={referenceSearch}
              onChange={(e) => setReferenceSearch(e.target.value)}
              className="flex-1 rounded-md border border-stone-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">
                {t("dateFrom")}
              </label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="rounded-md border border-stone-300 px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">
                {t("dateTo")}
              </label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="rounded-md border border-stone-300 px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            {hasFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="gap-1 text-muted-foreground"
              >
                <X className="h-3.5 w-3.5" />
                {t("clearFilters")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex py-8 items-center justify-center">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            </div>
          ) : smsRecords.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t("noSms")}
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 pr-4">{t("date")}</th>
                      <th className="pb-2 pr-4">{t("sender")}</th>
                      <th className="pb-2 pr-4">{t("amount")}</th>
                      <th className="pb-2 pr-4">{t("phone")}</th>
                      <th className="pb-2 pr-4">{t("reference")}</th>
                      <th className="pb-2">{t("processingStatus")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {smsRecords.map((r) => (
                      <tr
                        key={r.id}
                        className="border-b last:border-0 align-top"
                      >
                        <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
                          {new Date(r.sms_received_at).toLocaleDateString(
                            locale,
                            {
                              day: "2-digit",
                              month: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            }
                          )}
                        </td>
                        <td className="py-2 pr-4">{r.sender}</td>
                        <td className="py-2 pr-4 font-medium">
                          {r.parsed_amount != null
                            ? `${r.parsed_amount.toLocaleString()} FCFA`
                            : "—"}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">
                          {r.parsed_phone ?? "—"}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs truncate max-w-[120px]">
                          {r.parsed_reference ?? "—"}
                        </td>
                        <td className="py-2">
                          <Badge
                            variant={
                              STATUS_VARIANT[r.processing_status] ?? "outline"
                            }
                          >
                            {statusLabel(statusesMap, r.processing_status)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between pt-4 border-t mt-4">
                <p className="text-sm text-muted-foreground">
                  {t("showing", {
                    from: showFrom,
                    to: showTo,
                    total,
                  })}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  >
                    <ChevronLeft className="h-4 w-4 mr-1" />
                    {t("previous")}
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    {currentPage} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset + PAGE_SIZE >= total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    {t("next")}
                    <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
