"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Home,
  BookOpen,
  CreditCard,
  Bot,
  Settings,
  User,
  ChevronLeft,
  ChevronRight,
  Menu,
} from "lucide-react";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const t = useTranslations("Navigation");
  const tCommon = useTranslations("Common");
  const pathname = usePathname();
  const locale = useLocale();
  const [isCollapsed, setIsCollapsed] = useState(false);

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
      href: `/${locale}/settings`,
      label: t("settings"),
      icon: Settings,
      description: t("settingsDescription")
    },
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
          <div className="p-2">
            <LocaleSwitcher />
          </div>
        ) : (
          <div className="flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11 min-w-11 p-2"
              aria-label={t("languageSettings")}
            >
              <Menu className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
    </aside>
  );
}
