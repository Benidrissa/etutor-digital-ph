import { getTranslations } from "next-intl/server";
import { AuditLogClient } from "@/components/admin/audit-log-client";

export default async function AdminAuditLogsPage() {
  const t = await getTranslations("Admin.auditLog");

  return (
    <div className="p-4 md:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>
      </div>
      <AuditLogClient />
    </div>
  );
}
