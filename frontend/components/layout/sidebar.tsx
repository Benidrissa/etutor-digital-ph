"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
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
  LogOut,
} from "lucide-react";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/hooks/use-auth";

export function Sidebar() {
  const t = useTranslations("Navigation");
  const tCommon = useTranslations("Common");
  const tAuth = useTranslations("Auth");
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { user, logout } = useAuth();

  const handleLogout = async () => {
    try {
      await logout();
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  const navItems = [
    { 
      href: "/dashboard", 
      label: t("dashboard"), 
      icon: Home,
      description: t("dashboardDescription") 
    },
    { 
      href: "/modules", 
      label: t("modules"), 
      icon: BookOpen,
      description: t("modulesDescription") 
    },
    { 
      href: "/flashcards", 
      label: t("flashcards"), 
      icon: CreditCard,
      description: t("flashcardsDescription") 
    },
    { 
      href: "/tutor", 
      label: t("tutor"), 
      icon: Bot,
      description: t("tutorDescription") 
    },
    { 
      href: "/profile", 
      label: t("profile"), 
      icon: User,
      description: t("profileDescription") 
    },
    { 
      href: "/settings", 
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
      
      <div className="border-t p-2 space-y-2">
        {/* User info section */}
        {!isCollapsed && user && (
          <div className="p-2 rounded-md bg-muted/50">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm font-semibold">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{user.name}</p>
                <p className="text-xs text-muted-foreground truncate">{user.email}</p>
              </div>
            </div>
          </div>
        )}

        {/* Language switcher */}
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

        {/* Logout button */}
        <div className={cn("p-2", isCollapsed && "flex justify-center")}>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className={cn(
              "min-h-11 text-destructive hover:text-destructive hover:bg-destructive/10",
              isCollapsed 
                ? "min-w-11 p-2" 
                : "w-full justify-start gap-3 px-3"
            )}
            aria-label={tAuth("logout")}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {!isCollapsed && <span>{tAuth("logout")}</span>}
          </Button>
        </div>
      </div>
    </aside>
  );
}
