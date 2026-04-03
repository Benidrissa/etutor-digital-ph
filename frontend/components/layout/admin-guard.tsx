"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";

type AdminRole = "admin" | "expert";

interface AdminGuardProps {
  children: React.ReactNode;
  allowedRoles?: AdminRole[];
}

function getStoredRole(): string | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem("access_token");
  if (!token) return null;
  try {
    const [, payload] = token.split(".");
    const decoded = JSON.parse(atob(payload));
    return decoded?.role ?? null;
  } catch {
    return null;
  }
}

export function AdminGuard({
  children,
  allowedRoles = ["admin", "expert"],
}: AdminGuardProps) {
  const router = useRouter();
  const locale = useLocale();
  const [authorized] = useState<boolean>(() => {
    const role = getStoredRole();
    return role !== null && (allowedRoles as string[]).includes(role);
  });

  useEffect(() => {
    if (!authorized) {
      router.replace(`/${locale}/dashboard`);
    }
  }, [authorized, locale, router]);

  if (!authorized) return null;

  return <>{children}</>;
}
