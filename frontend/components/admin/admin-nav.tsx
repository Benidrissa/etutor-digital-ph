"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { cn } from "@/lib/utils";

export function AdminNav() {
  const t = useTranslations("Admin");
  const locale = useLocale();
  const pathname = usePathname();

  const items = [
    { href: `/${locale}/admin/users`, label: t("users.title") },
    { href: `/${locale}/admin/courses`, label: t("courses.title") },
    { href: `/${locale}/admin/taxonomy`, label: t("taxonomy.title") },
    { href: `/${locale}/admin/syllabus`, label: t("syllabus.title") },
    { href: `/${locale}/admin/settings`, label: t("settings.title") },
    { href: `/${locale}/admin/analytics`, label: t("analytics.title") },
    { href: `/${locale}/admin/audit-logs`, label: t("auditLog.title") },
    { href: `/${locale}/admin/payments`, label: t("payments.title") },
  ];

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
