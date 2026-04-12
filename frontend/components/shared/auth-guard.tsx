"use client";

import { startTransition, useEffect, useState } from "react";
import { useRouter } from "@/i18n/routing";
import { useLocale } from "next-intl";
import { usePathname } from "next/navigation";
import { identifyUser } from "@/lib/analytics";

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

function isTokenExpired(token: string): boolean {
  try {
    const payload = token.split(".")[1];
    if (!payload) return true;
    const decoded = JSON.parse(atob(payload));
    if (!decoded.exp) return false;
    return decoded.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

/** Routes inside the (app) layout that should be accessible without authentication. */
const PUBLIC_APP_PATHS = [
  /^\/[a-z]{2}\/courses$/,
  /^\/[a-z]{2}\/courses\/[^/]+$/,
];

function isPublicAppPath(pathname: string): boolean {
  return PUBLIC_APP_PATHS.some((p) => p.test(pathname));
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const locale = useLocale();
  const pathname = usePathname();
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    // Allow public routes through without authentication
    if (isPublicAppPath(pathname)) {
      startTransition(() => setAuthorized(true));
      return;
    }

    const token = getStoredToken();
    if (!token || isTokenExpired(token)) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("user");
      router.replace("/login");
      return;
    }
    const storedUser = localStorage.getItem("user");
    if (storedUser) {
      try {
        const user = JSON.parse(storedUser) as {
          id?: string;
          country?: string;
          current_level?: number;
          preferred_language?: string;
        };
        if (user.id) {
          identifyUser(user.id, {
            country: user.country,
            level: user.current_level,
            preferred_language: user.preferred_language,
          });
        }
      } catch {
        // ignore malformed user data
      }
    }
    startTransition(() => setAuthorized(true));
  }, [locale, pathname, router]);

  if (!authorized) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return <>{children}</>;
}
