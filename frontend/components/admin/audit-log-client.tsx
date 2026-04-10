"use client";

import { useTranslations, useLocale } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";

interface AuditLogEntry {
  id: string;
  admin_id: string | null;
  admin_email: string | null;
  target_user_id: string | null;
  target_user_email: string | null;
  action: string;
  details: string | null;
  created_at: string;
}

const ACTION_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  deactivate_user: "destructive",
  reactivate_user: "default",
  promote_to_expert: "secondary",
  promote_to_admin: "secondary",
  demote_to_user: "outline",
  update_role: "outline",
};

export function AuditLogClient({ userId }: { userId?: string }) {
  const t = useTranslations("Admin.auditLog");
  const locale = useLocale();

  const queryParams = userId ? `?target_user_id=${userId}&limit=50` : "?limit=50";

  const { data: logs, isLoading, error } = useQuery<AuditLogEntry[]>({
    queryKey: ["admin", "audit-logs", userId],
    queryFn: () => apiFetch<AuditLogEntry[]>(`/api/v1/admin/audit-logs${queryParams}`),
  });

  if (isLoading) {
    return <p className="py-8 text-center text-muted-foreground">{t("loading")}</p>;
  }

  if (error) {
    return <p className="py-8 text-center text-destructive" role="alert">{t("error")}</p>;
  }

  if (!logs || logs.length === 0) {
    return <p className="py-8 text-center text-muted-foreground">{t("noLogs")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-muted-foreground text-left">
            <th className="pb-2 pr-4">{t("date")}</th>
            <th className="pb-2 pr-4">{t("adminEmail")}</th>
            <th className="pb-2 pr-4">{t("targetUser")}</th>
            <th className="pb-2 pr-4">{t("action")}</th>
            <th className="pb-2">{t("details")}</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => {
            const actionLabel =
              t.raw("actions") &&
              typeof t.raw("actions") === "object" &&
              (t.raw("actions") as Record<string, string>)[log.action]
                ? (t.raw("actions") as Record<string, string>)[log.action]
                : log.action;

            return (
              <tr key={log.id} className="border-b last:border-0 align-top">
                <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
                  {new Date(log.created_at).toLocaleDateString(locale, {
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </td>
                <td className="py-2 pr-4 truncate max-w-[140px]">{log.admin_email ?? "—"}</td>
                <td className="py-2 pr-4 truncate max-w-[140px]">
                  {log.target_user_email ?? "—"}
                </td>
                <td className="py-2 pr-4">
                  <Badge variant={ACTION_VARIANT[log.action] ?? "outline"}>
                    {actionLabel}
                  </Badge>
                </td>
                <td className="py-2 text-muted-foreground">{log.details ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
