"use client";

import { startTransition, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useLocale } from "next-intl";

function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const locale = useLocale();
  const pathname = usePathname();
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      router.replace(`/${locale}/dashboard`);
      return;
    }
    const payload = parseJwtPayload(token);
    const role = payload?.role as string | undefined;
    if (role === "admin" || role === "sub_admin" || role === "expert") {
      startTransition(() => setAuthorized(true));
    } else {
      router.replace(`/${locale}/dashboard`);
    }
  }, [locale, pathname, router]);

  if (!authorized) return null;

  return <>{children}</>;
}
