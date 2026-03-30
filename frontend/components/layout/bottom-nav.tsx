"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

export function BottomNav() {
  const t = useTranslations("Navigation");

  const navItems = [
    { href: "/dashboard", label: t("dashboard") },
    { href: "/modules", label: t("modules") },
    { href: "/flashcards", label: t("flashcards") },
    { href: "/tutor", label: t("tutor") },
    { href: "/settings", label: t("settings") },
  ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 border-t bg-card md:hidden">
      <div className="flex items-center justify-around">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="flex min-h-12 min-w-12 flex-1 flex-col items-center justify-center py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <span>{item.label}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}
