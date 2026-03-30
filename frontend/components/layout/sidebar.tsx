"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";

export function Sidebar() {
  const t = useTranslations("Navigation");
  const tCommon = useTranslations("Common");

  const navItems = [
    { href: "/dashboard", label: t("dashboard") },
    { href: "/modules", label: t("modules") },
    { href: "/flashcards", label: t("flashcards") },
    { href: "/tutor", label: t("tutor") },
    { href: "/settings", label: t("settings") },
  ];

  return (
    <aside className="hidden w-60 shrink-0 border-r bg-card md:block">
      <div className="flex h-14 items-center border-b px-4">
        <span className="text-sm font-semibold">{tCommon("appName")}</span>
      </div>
      <nav className="flex flex-col gap-1 p-2">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mt-auto border-t p-4">
        <LocaleSwitcher />
      </div>
    </aside>
  );
}
