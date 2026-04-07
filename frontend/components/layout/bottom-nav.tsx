"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Home,
  GraduationCap,
  CreditCard,
  Bot,
  MoreHorizontal,
  BookOpen,
  User,
  Settings,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useState, useEffect, useRef } from "react";
import { getCurriculumContext } from "@/lib/curriculum-context";

export function BottomNav() {
  const t = useTranslations("Navigation");
  const pathname = usePathname();
  const locale = useLocale();
  const [moreOpen, setMoreOpen] = useState(false);
  const [curriculumSlug, setCurriculumSlug] = useState<string | null>(null);
  const moreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCurriculumSlug(getCurriculumContext());
  }, [pathname]);

  useEffect(() => {
    if (!moreOpen) return;
    function handleOutside(e: MouseEvent) {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [moreOpen]);

  const primaryItems = [
    {
      href: curriculumSlug
        ? `/${locale}/dashboard?curriculum=${curriculumSlug}`
        : `/${locale}/dashboard`,
      label: t("dashboard"),
      icon: Home,
      description: t("dashboardDescription"),
    },
    {
      href: curriculumSlug
        ? `/${locale}/curricula/${curriculumSlug}`
        : `/${locale}/courses`,
      label: t("courses"),
      icon: GraduationCap,
      description: t("coursesDescription"),
    },
    {
      href: `/${locale}/flashcards`,
      label: t("flashcards"),
      icon: CreditCard,
      description: t("flashcardsDescription"),
    },
    {
      href: `/${locale}/tutor`,
      label: t("tutor"),
      icon: Bot,
      description: t("tutorDescription"),
    },
  ];

  const moreItems = [
    {
      href: `/${locale}/modules`,
      label: t("modules"),
      icon: BookOpen,
      description: t("modulesDescription"),
    },
    {
      href: `/${locale}/profile`,
      label: t("profile"),
      icon: User,
      description: t("profileDescription"),
    },
    {
      href: `/${locale}/settings`,
      label: t("settings"),
      icon: Settings,
      description: t("settingsDescription"),
    },
  ];

  const isMoreActive = moreItems.some((item) => pathname.includes(item.href));

  return (
    <div ref={moreRef} className="fixed bottom-0 left-0 right-0 z-50 md:hidden">
      {moreOpen && (
        <div
          className="border-t bg-card shadow-lg"
          role="menu"
          aria-label={t("moreMenuLabel")}
        >
          <div className="flex items-center justify-between border-b px-4 py-2">
            <span className="text-sm font-medium text-foreground">
              {t("more")}
            </span>
            <button
              className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
              onClick={() => setMoreOpen(false)}
              aria-label={t("closeMoreMenu")}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <div className="grid grid-cols-3 gap-1 p-2">
            {moreItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname.includes(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  role="menuitem"
                  onClick={() => setMoreOpen(false)}
                  className={cn(
                    "flex min-h-[56px] flex-col items-center justify-center gap-1 rounded-md px-2 py-3 text-xs transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  )}
                  aria-label={item.description}
                  aria-current={isActive ? "page" : undefined}
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                  <span className={cn("text-xs", isActive && "font-medium")}>
                    {item.label}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <nav
        className="border-t bg-card"
        role="navigation"
        aria-label={t("mobileNavigation")}
      >
        <div className="flex items-center justify-around">
          {primaryItems.map((item) => {
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
                <span
                  className={cn(
                    "text-xs",
                    isActive && "text-primary font-medium"
                  )}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}

          <button
            className={cn(
              "flex min-h-11 min-w-11 flex-1 flex-col items-center justify-center py-2 text-xs transition-colors",
              (moreOpen || isMoreActive)
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => setMoreOpen((prev) => !prev)}
            aria-label={t("moreMenuLabel")}
            aria-expanded={moreOpen}
            aria-haspopup="menu"
          >
            <MoreHorizontal
              className={cn(
                "h-5 w-5 mb-1",
                (moreOpen || isMoreActive) && "text-primary"
              )}
              aria-hidden="true"
            />
            <span
              className={cn(
                "text-xs",
                (moreOpen || isMoreActive) && "text-primary font-medium"
              )}
            >
              {t("more")}
            </span>
          </button>
        </div>
      </nav>
    </div>
  );
}
