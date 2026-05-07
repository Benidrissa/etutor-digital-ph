"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getReviewQueue } from "@/lib/api-quality";

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

const QUALITY_ROLES = new Set(["admin", "sub_admin", "expert"]);

export function AdminNav() {
  const t = useTranslations("Admin");
  const locale = useLocale();
  const pathname = usePathname();
  const role = useMemo(() => getRole(), []);

  // Pull the cross-course attention count for the Quality nav badge.
  // Refetches on focus and every 5 min; only fires for roles that can read.
  const queueQ = useQuery({
    queryKey: ["admin", "quality", "nav-badge"],
    queryFn: () => getReviewQueue({ hasIssues: true, limit: 200 }),
    enabled: role !== null && QUALITY_ROLES.has(role),
    staleTime: 5 * 60 * 1000,
    refetchInterval: false,
  });
  const attentionCount =
    queueQ.data?.reduce(
      (acc, c) => acc + c.units_needs_review_final + c.units_failed,
      0,
    ) ?? 0;

  const allItems = [
    { href: `/${locale}/admin/users`, label: t("users.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/courses`, label: t("courses.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/quality`, label: t("quality.title"), adminOnly: false, badge: attentionCount },
    { href: `/${locale}/admin/curricula`, label: t("curricula.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/groups`, label: t("groups.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/taxonomy`, label: t("taxonomy.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/syllabus`, label: t("syllabus.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/settings`, label: t("settings.title"), adminOnly: true, badge: 0 },
    { href: `/${locale}/admin/analytics`, label: t("analytics.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/audit-logs`, label: t("auditLog.title"), adminOnly: false, badge: 0 },
    { href: `/${locale}/admin/payments`, label: t("payments.title"), adminOnly: false, badge: 0 },
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
              "shrink-0 inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium transition-colors",
              isActive
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            aria-current={isActive ? "page" : undefined}
          >
            {item.label}
            {item.badge > 0 && (
              <span
                className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-semibold text-white"
                aria-label={`${item.badge}`}
              >
                {item.badge}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
