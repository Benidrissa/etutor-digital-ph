"use client";

import Link from "next/link";
import { startTransition, useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Home,
  BookOpen,
  GraduationCap,
  CreditCard,
  Bot,
  User,
  ChevronLeft,
  ChevronRight,
  Menu,
  LogOut,
  Building2,
  ShieldCheck,
  Wallet,
  Award,
  ListChecks,
  Library,
} from "lucide-react";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { authClient } from "@/lib/auth";
import { useQueryClient } from "@tanstack/react-query";
import { getCurriculumContext, onCurriculumContextChange, type CurriculumContextValue } from "@/lib/curriculum-context";

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

export function Sidebar() {
  const t = useTranslations("Navigation");
  const tCommon = useTranslations("Common");
  const pathname = usePathname();
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [curriculumCtx, setCurriculumCtx] = useState<CurriculumContextValue | null>(null);

  useEffect(() => {
    startTransition(() => {
      setUserRole(getUserRole());
      setCurriculumCtx(getCurriculumContext());
    });
  }, [pathname]);

  useEffect(() => {
    return onCurriculumContextChange(() => {
      startTransition(() => {
        setCurriculumCtx(getCurriculumContext());
      });
    });
  }, []);

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await authClient.logout();
      queryClient.clear();
      router.push(`/${locale}/login`);
    } catch {
      setIsLoggingOut(false);
    }
  };

  const navItems = [
    {
      href: curriculumCtx
        ? `/${locale}/dashboard?curriculum=${curriculumCtx.slug}`
        : `/${locale}/dashboard`,
      label: t("dashboard"),
      icon: Home,
      description: t("dashboardDescription")
    },
    {
      href: curriculumCtx
        ? curriculumCtx.orgSlug
          ? `/${locale}/org/${curriculumCtx.orgSlug}/curricula/${curriculumCtx.slug}`
          : `/${locale}/curricula/${curriculumCtx.slug}`
        : `/${locale}/courses`,
      label: t("courses"),
      icon: GraduationCap,
      description: t("coursesDescription")
    },
    {
      href: `/${locale}/qbank`,
      label: t("qbank"),
      icon: ListChecks,
      description: t("qbankDescription")
    },
    {
      href: `/${locale}/curricula`,
      label: t("curricula"),
      icon: Library,
      description: t("curriculaDescription")
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
      href: `/${locale}/certificates`,
      label: t("certificates"),
      icon: Award,
      description: t("certificatesDescription")
    },
    {
      href: `/${locale}/tutor`,
      label: t("tutor"),
      icon: Bot,
      description: t("tutorDescription")
    },
    {
      href: `/${locale}/profile`,
      label: t("profile"),
      icon: User,
      description: t("profileDescription")
    },
    {
      href: `/${locale}/subscribe`,
      label: t("subscribe"),
      icon: Wallet,
      description: t("subscribeDescription")
    },
    ...(userRole === "admin" || userRole === "sub_admin"
      ? [
          {
            href: `/${locale}/organizations`,
            label: t("organizations"),
            icon: Building2,
            description: t("organizationsDescription"),
          },
        ]
      : []),
    ...(userRole === "admin" || userRole === "sub_admin" || userRole === "expert"
      ? [
          {
            href: `/${locale}/admin/users`,
            label: t("admin"),
            icon: ShieldCheck,
            description: t("adminDescription"),
          },
        ]
      : []),
  ];

  return (
    <aside 
      className={cn(
        "hidden shrink-0 border-r bg-card md:flex md:flex-col transition-all duration-300",
        isCollapsed ? "w-16" : "w-60"
      )}
      role="navigation"
      aria-label={t("desktopNavigation")}
    >
      <div className={cn(
        "flex h-14 items-center border-b",
        isCollapsed ? "px-2 justify-center" : "px-4 justify-between"
      )}>
        {!isCollapsed && (
          <span className="text-sm font-semibold truncate">
            {tCommon("appName")}
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="min-h-11 min-w-11 p-2"
          aria-label={isCollapsed ? t("expandSidebar") : t("collapseSidebar")}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>
      
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname.includes(item.href);
          
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors min-h-11",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                isCollapsed && "justify-center px-2"
              )}
              title={isCollapsed ? item.description : undefined}
              aria-label={item.description}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon 
                className="h-4 w-4 shrink-0" 
                aria-hidden="true"
              />
              {!isCollapsed && (
                <span className="truncate">{item.label}</span>
              )}
            </Link>
          );
        })}
      </nav>
      
      <div className="border-t p-2">
        {!isCollapsed ? (
          <div className="space-y-1 p-2">
            <LocaleSwitcher />
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-destructive hover:bg-destructive/10 hover:text-destructive min-h-11"
              onClick={handleLogout}
              disabled={isLoggingOut}
              aria-label={t("logoutDescription")}
            >
              <LogOut className="mr-2 h-4 w-4" aria-hidden="true" />
              {t("logout")}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11 min-w-11 p-2"
              aria-label={t("languageSettings")}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11 min-w-11 p-2 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={handleLogout}
              disabled={isLoggingOut}
              aria-label={t("logoutDescription")}
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        )}
      </div>
    </aside>
  );
}
