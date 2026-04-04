"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { cn } from "@/lib/utils";

export function ExpertNav() {
  const t = useTranslations("Expert");
  const locale = useLocale();
  const pathname = usePathname();

  const items = [
    { href: `/${locale}/expert/dashboard`, label: t("dashboard") },
    { href: `/${locale}/expert/courses`, label: t("myCourses") },
    { href: `/${locale}/expert/revenue`, label: t("revenue") },
    { href: `/${locale}/expert/credits`, label: t("credits") },
  ];

  return (
    <nav className="flex gap-1 border-b px-4 md:px-6 overflow-x-auto" aria-label="Expert navigation">
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
