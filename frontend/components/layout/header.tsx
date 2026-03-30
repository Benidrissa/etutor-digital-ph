"use client";

import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";

export function Header() {
  const tCommon = useTranslations("Common");

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 md:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <span className="text-lg font-semibold">{tCommon("appName")}</span>
        <LocaleSwitcher />
      </div>
    </header>
  );
}