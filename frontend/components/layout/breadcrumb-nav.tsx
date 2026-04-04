"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { ChevronRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";

interface BreadcrumbItem {
  label: string;
  href?: string;
  current?: boolean;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function BreadcrumbNav() {
  const pathname = usePathname();
  const t = useTranslations("Navigation");
  const locale = useLocale();
  const [moduleNames, setModuleNames] = useState<Record<string, string>>({});

  // Fetch module title when path contains a UUID after /modules/
  useEffect(() => {
    const segments = pathname.split("/").filter(Boolean).slice(1);
    const modIdx = segments.indexOf("modules");
    if (modIdx >= 0 && modIdx + 1 < segments.length) {
      const id = segments[modIdx + 1];
      if (UUID_RE.test(id) && !moduleNames[id]) {
        import("@/lib/api").then(({ getModuleDetailWithProgress }) =>
          getModuleDetailWithProgress(id)
            .then((mod) => {
              const title = locale === "fr" ? mod.title_fr : mod.title_en;
              if (title) setModuleNames((prev) => ({ ...prev, [id]: title }));
            })
            .catch(() => {})
        );
      }
    }
  }, [pathname, locale, moduleNames]);

  // Generate breadcrumb items based on current path
  const generateBreadcrumbs = (): BreadcrumbItem[] => {
    const segments = pathname.split('/').filter(Boolean);

    // Remove locale from segments (first segment in our app structure)
    const pathSegments = segments.slice(1);

    const breadcrumbs: BreadcrumbItem[] = [
      {
        label: t("dashboard"),
        href: `/${locale}/dashboard`,
        current: pathSegments.length === 0 || pathSegments[0] === 'dashboard'
      }
    ];

    // Build breadcrumb trail based on path
    for (let i = 0; i < pathSegments.length; i++) {
      const segment = pathSegments[i];
      const isLast = i === pathSegments.length - 1;

      // Skip if it's already the dashboard
      if (segment === 'dashboard') continue;

      let label = segment;
      const href = `/${locale}/${pathSegments.slice(0, i + 1).join('/')}`;

      // Map segments to readable labels
      switch (segment) {
        case 'modules':
          label = t("modules");
          break;
        case 'flashcards':
          label = t("flashcards");
          break;
        case 'tutor':
          label = t("tutor");
          break;
        case 'settings':
          label = t("settings");
          break;
        case 'lessons':
          label = t("lessons");
          break;
        case 'quiz':
          label = t("quiz");
          break;
        case 'case-study':
          label = t("caseStudy");
          break;
        default:
          // Resolve UUIDs to readable names (e.g., module titles)
          if (UUID_RE.test(segment) && moduleNames[segment]) {
            label = moduleNames[segment];
          } else if (UUID_RE.test(segment)) {
            // Skip showing raw UUIDs — will resolve on next render
            continue;
          } else {
            label = segment.charAt(0).toUpperCase() + segment.slice(1);
          }
      }

      breadcrumbs.push({
        label,
        href: isLast ? undefined : href,
        current: isLast
      });
    }

    return breadcrumbs;
  };

  const breadcrumbs = generateBreadcrumbs();

  // Don't show breadcrumbs if only one item (dashboard)
  if (breadcrumbs.length <= 1) {
    return null;
  }

  return (
    <nav 
      className="hidden md:flex items-center space-x-1 text-sm text-muted-foreground py-3 px-6 bg-card/50"
      aria-label={t("breadcrumbNavigation")}
    >
      <Home className="h-4 w-4" aria-hidden="true" />
      <ChevronRight className="h-4 w-4" aria-hidden="true" />
      
      {breadcrumbs.map((item, index) => (
        <div key={index} className="flex items-center">
          {item.href && !item.current ? (
            <Link
              href={item.href}
              className="hover:text-foreground transition-colors"
              aria-label={`${t("navigateTo")} ${item.label}`}
            >
              {item.label}
            </Link>
          ) : (
            <span 
              className={cn(
                item.current && "text-foreground font-medium"
              )}
              aria-current={item.current ? "page" : undefined}
            >
              {item.label}
            </span>
          )}
          
          {index < breadcrumbs.length - 1 && (
            <ChevronRight className="h-4 w-4 mx-1" aria-hidden="true" />
          )}
        </div>
      ))}
    </nav>
  );
}