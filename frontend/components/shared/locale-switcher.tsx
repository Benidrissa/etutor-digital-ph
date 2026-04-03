"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export function LocaleSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("LanguageSwitcher");

  // Save locale preference to localStorage whenever it changes
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("preferred-locale", locale);
    }
  }, [locale]);

  function switchLocale() {
    const nextLocale = locale === "fr" ? "en" : "fr";
    const newPath = pathname.replace(`/${locale}`, `/${nextLocale}`);
    
    // Save preference before switching
    if (typeof window !== "undefined") {
      localStorage.setItem("preferred-locale", nextLocale);
    }
    
    router.push(newPath);
  }

  // Get flag emoji for current locale
  const getFlagIcon = (loc: string) => {
    switch (loc) {
      case "fr":
        return "🇫🇷";
      case "en":
        return "🇬🇧";
      default:
        return "🌐";
    }
  };

  const getLanguageAbbrev = (loc: string) => {
    return loc.toUpperCase();
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={switchLocale}
      className="flex min-h-11 min-w-[60px] items-center gap-2 px-3"
      title={t("switchTo")}
      aria-label={t("switchTo")}
    >
      <span className="text-sm font-medium">
        {getLanguageAbbrev(locale)}
      </span>
    </Button>
  );
}
