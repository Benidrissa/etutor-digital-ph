"use client";

import { useLocale } from "next-intl";
import { useRouter, usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";

export function LocaleSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();

  function switchLocale() {
    const nextLocale = locale === "fr" ? "en" : "fr";
    const newPath = pathname.replace(`/${locale}`, `/${nextLocale}`);
    router.push(newPath);
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={switchLocale}
      className="min-h-9 min-w-9"
    >
      {locale === "fr" ? "EN" : "FR"}
    </Button>
  );
}
