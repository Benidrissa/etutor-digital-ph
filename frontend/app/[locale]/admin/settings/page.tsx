"use client";

import { useMemo } from "react";
import { redirect } from "next/navigation";
import { useLocale } from "next-intl";
import { SettingsClient } from "@/components/admin/settings-client";

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

export default function AdminSettingsPage() {
  const locale = useLocale();
  const role = useMemo(() => getRole(), []);

  if (role !== "admin") {
    redirect(`/${locale}/admin`);
  }

  return <SettingsClient />;
}
