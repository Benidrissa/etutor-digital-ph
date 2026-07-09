"use client";

import { useMemo } from "react";
import { redirect } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { ApiKeysCard } from "@/components/admin/api-keys-card";

function getRole(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64));
    return (payload?.role as string) ?? null;
  } catch {
    return null;
  }
}

// Tenant owner (admin) + delegated staff (sub_admin) can manage provider keys.
// Expert is admitted to /admin by AdminGuard, so guard the page explicitly.
export default function AdminApiKeysPage() {
  const locale = useLocale();
  const t = useTranslations("Admin.apiKeys");
  const role = useMemo(() => getRole(), []);

  if (role !== "admin" && role !== "sub_admin") {
    redirect(`/${locale}/admin`);
  }

  return (
    <div className="px-4 py-6 md:px-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("pageSubtitle")}</p>
      </div>
      <ApiKeysCard />
    </div>
  );
}
