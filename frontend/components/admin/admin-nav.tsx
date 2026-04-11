"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { useMemo } from "react";
import { cn } from "@/lib/utils";

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

export function AdminNav() {
  const t = useTranslations("Admin");
  const locale = useLocale();
  const pathname = usePathname();
  const role = useMemo(() => getRole(), []);

  const allItems = [
    { href: `/${locale}/admin/users`, label: t("users.title"), adminOnly: false },
    { href: `/${locale}/admin/courses`, label: t("courses.title"), adminOnly: false },
    { href: `/${locale}/admin/curricula`, label: t("curricula.title"), adminOnly: false },
    { href: `/${locale}/admin/groups`, label: t("groups.title"), adminOnly: false },
    { href: `/${locale}/admin/taxonomy`, label: t("taxonomy.title"), adminOnly: false },
    { href: `/${locale}/admin/syllabus`, label: t("syllabus.title"), adminOnly: false },
    { href: `/${locale}/admin/settings`, label: t("settings.title"), adminOnly: true },
    { href: `/${locale}/admin/analytics`, label: t("analytics.title"), adminOnly: false },
    { href: `/${locale}/admin/audit-logs`, label: t("auditLog.title"), adminOnly: false },
    { href: `/${locale}/admin/payments`, label: t("payments.title"), adminOnly: false },
  ];

  const items = allItems.filter((item) => !item.adminOnly || role === "admin");

  return (
    <nav className="flex gap-1 border-b px-4 md:px-6 overflow-x-auto" aria-label="Admin navigation">
      {items.map((item) => {
        const isActive = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors",
              isActive
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            aria-current={isActive ? "page" : undefined}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
