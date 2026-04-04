"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Home,
  BookOpen,
  CreditCard,
  Bot,
  ShoppingBag,
} from "lucide-react";
import { cn } from "@/lib/utils";

export function BottomNav() {
  const t = useTranslations("Navigation");
  const pathname = usePathname();
  const locale = useLocale();

  const navItems = [
    {
      href: `/${locale}/dashboard`,
      label: t("dashboard"),
      icon: Home,
      description: t("dashboardDescription")
    },
    {
      href: `/${locale}/modules`,
      label: t("modules"),
      icon: BookOpen,
      description: t("modulesDescription")
    },
    {
      href: `/${locale}/flashcards`,
      label: t("flashcards"),
      icon: CreditCard,
      description: t("flashcardsDescription")
    },
    {
      href: `/${locale}/marketplace`,
      label: t("marketplace"),
      icon: ShoppingBag,
      description: t("marketplaceDescription")
    },
    {
      href: `/${locale}/tutor`,
      label: t("tutor"),
      icon: Bot,
      description: t("tutorDescription")
    },
  ];

  return (
    <nav 
      className="fixed bottom-0 left-0 right-0 z-50 border-t bg-card md:hidden"
      role="navigation"
      aria-label={t("mobileNavigation")}
    >
      <div className="flex items-center justify-around">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname.includes(item.href);
          
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex min-h-11 min-w-11 flex-1 flex-col items-center justify-center py-2 text-xs transition-colors",
                isActive
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              aria-label={item.description}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon 
                className={cn(
                  "h-5 w-5 mb-1",
                  isActive && "text-primary"
                )} 
                aria-hidden="true"
              />
              <span className={cn(
                "text-xs",
                isActive && "text-primary font-medium"
              )}>
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
