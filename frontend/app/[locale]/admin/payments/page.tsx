"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";

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

export default function PaymentsPage() {
  const t = useTranslations("Admin.payments");
  const locale = useLocale();

  const [relayStatus, setRelayStatus] = useState<RelayStatus | null>(null);
  const [smsRecords, setSmsRecords] = useState<SmsRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");

  const fetchData = useCallback(
    async (filter: string) => {
      setLoading(true);
      try {
        const qs = filter ? `?status_filter=${filter}` : "";
        const [status, sms] = await Promise.all([
          apiFetch<RelayStatus>("/api/v1/admin/relay/status"),
          apiFetch<SmsRecord[]>(`/api/v1/admin/relay/sms${qs}`),
        ]);
        setRelayStatus(status);
        setSmsRecords(sms);
      } catch {
        setRelayStatus(null);
        setSmsRecords([]);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    fetchData(statusFilter);
  }, [statusFilter, fetchData]);

  if (loading) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-6">
        <h1 className="text-2xl font-bold mb-1">{t("title")}</h1>
        <div className="flex min-h-[40vh] items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
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
                      <td className="py-2 pr-4">
                        {d.signal != null
                          ? "▪".repeat(d.signal) + "▫".repeat(4 - d.signal)
                          : "—"}
                      </td>
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
        <CardHeader className="pb-2">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <CardTitle className="text-base">{t("smsRecords")}</CardTitle>
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
          </div>
        </CardHeader>
        <CardContent>
          {smsRecords.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t("noSms")}
            </p>
          ) : (
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
                  {smsRecords.map((r) => {
                    const statusLabel =
                      (
                        t.raw("statuses") as Record<string, string> | undefined
                      )?.[r.processing_status] ?? r.processing_status;
                    return (
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
                            {statusLabel}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
