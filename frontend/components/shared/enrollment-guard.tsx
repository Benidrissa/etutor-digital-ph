"use client";

import { useEffect, useState } from "react";
import { useRouter } from "@/i18n/routing";
import { useLocale, useTranslations } from "next-intl";
import { API_BASE } from "@/lib/api";

interface EnrollmentGuardProps {
  moduleId: string;
  children: React.ReactNode;
}

async function fetchEnrollmentStatus(moduleId: string, token: string): Promise<boolean> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/progress/modules/${encodeURIComponent(moduleId)}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      }
    );
    if (res.status === 401 || res.status === 403) return false;
    if (!res.ok) return false;
    return true;
  } catch {
    return false;
  }
}

function isAdmin(): boolean {
  try {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (token) {
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.role === "admin";
    }
  } catch {
    // ignore parse errors
  }
  return false;
}

export function EnrollmentGuard({ moduleId, children }: EnrollmentGuardProps) {
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations("EnrollmentGuard");
  const [guardStatus, setGuardStatus] = useState<"checking" | "allowed" | "denied">(
    () => (isAdmin() ? "allowed" : "checking")
  );

  useEffect(() => {
    if (guardStatus === "allowed") return;

    const token =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

    if (!token) {
      router.replace("/login");
      return;
    }

    fetchEnrollmentStatus(moduleId, token).then((enrolled) => {
      setGuardStatus(enrolled ? "allowed" : "denied");
    });
  }, [moduleId, router, locale, guardStatus]);

  if (guardStatus === "checking") {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (guardStatus === "denied") {
    return (
      <div className="container mx-auto max-w-2xl px-4 py-16 text-center">
        <div className="mx-auto w-16 h-16 bg-stone-100 rounded-full flex items-center justify-center mb-6">
          <span className="text-2xl">🔒</span>
        </div>
        <h2 className="text-2xl font-bold text-stone-900 mb-3">{t("title")}</h2>
        <p className="text-stone-600 mb-8">{t("description")}</p>
        <button
          onClick={() => router.replace("/courses")}
          className="inline-flex items-center justify-center rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground min-h-11 hover:bg-primary/90 transition-colors"
        >
          {t("cta")}
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
