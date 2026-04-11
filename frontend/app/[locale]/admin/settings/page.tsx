"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  const locale = useLocale();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    const role = getRole();
    if (role === "admin") {
      setAllowed(true);
    } else {
      setAllowed(false);
      router.replace(`/${locale}/admin`);
    }
  }, [locale, router]);

  if (allowed === null) return null;
  if (!allowed) return null;

  return <SettingsClient />;
}
