"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Home,
  GraduationCap,
  CreditCard,
  Bot,
  Brain,
  ListChecks,
  MoreHorizontal,
  BookOpen,
  User,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { startTransition, useState, useEffect, useRef } from "react";
import {
  getCurriculumContext,
  onCurriculumContextChange,
  type CurriculumContextValue,
} from "@/lib/curriculum-context";

function getUserRole(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64)) as Record<string, unknown>;
    return typeof payload?.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

export function BottomNav() {
  const t = useTranslations("Navigation");
  const pathname = usePathname();
  const locale = useLocale();
  const [moreOpen, setMoreOpen] = useState(false);
  const [curriculumCtx, setCurriculumCtx] =
    useState<CurriculumContextValue | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);
  const moreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    startTransition(() => {
      setCurriculumCtx(getCurriculumContext());
      setUserRole(getUserRole());
    });
  }, [pathname]);

  useEffect(() => {
    return onCurriculumContextChange(() => {
      startTransition(() => setCurriculumCtx(getCurriculumContext()));
    });
  }, []);

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
      href: curriculumCtx
        ? `/${locale}/dashboard?curriculum=${curriculumCtx.slug}`
        : `/${locale}/dashboard`,
      label: t("dashboard"),
      icon: Home,
      description: t("dashboardDescription"),
    },
    {
      href: curriculumCtx
        ? curriculumCtx.orgSlug
          ? `/${locale}/org/${curriculumCtx.orgSlug}/curricula/${curriculumCtx.slug}`
          : `/${locale}/curricula/${curriculumCtx.slug}`
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
      href: `/${locale}/qbank/tests`,
      label: t("qbankTests"),
      icon: ListChecks,
      description: t("qbankTestsDescription"),
    },
    ...(userRole === "admin" ||
    userRole === "sub_admin" ||
    userRole === "expert"
      ? [
          {
            href: `/${locale}/qbank`,
            label: t("qbank"),
            icon: Brain,
            description: t("qbankDescription"),
          },
        ]
      : []),
    {
      href: `/${locale}/profile`,
      label: t("profile"),
      icon: User,
      description: t("profileDescription"),
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
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
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
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-label={item.description}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon
                  className={cn("h-5 w-5", isActive && "text-primary")}
                  aria-hidden="true"
                />
              </Link>
            );
          })}

          <button
            className={cn(
              "flex min-h-11 min-w-11 flex-1 flex-col items-center justify-center py-2 text-xs transition-colors",
              moreOpen || isMoreActive
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setMoreOpen((prev) => !prev)}
            aria-label={t("moreMenuLabel")}
            aria-expanded={moreOpen}
            aria-haspopup="menu"
          >
            <MoreHorizontal
              className={cn(
                "h-5 w-5",
                (moreOpen || isMoreActive) && "text-primary",
              )}
              aria-hidden="true"
            />
          </button>
        </div>
      </nav>
    </div>
  );
}
