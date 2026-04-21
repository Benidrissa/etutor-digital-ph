"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useOrg } from "./org-context";
import { useCurrentUser } from "@/lib/hooks/use-current-user";
import { canEditBank, type OrgRole } from "@/lib/permissions";
import {
  LayoutDashboard,
  BookOpen,
  GraduationCap,
  QrCode,
  BarChart3,
  Users,
  Library,
  ClipboardList,
} from "lucide-react";

export function OrgNav() {
  const t = useTranslations("Organization");
  const locale = useLocale();
  const pathname = usePathname();
  const { org, role } = useOrg();
  const currentUser = useCurrentUser();
  const isEditor = canEditBank(role as OrgRole, currentUser?.role);

  if (!org) return null;

  const base = `/${locale}/org/${org.slug}`;
  const tabs = [
    { href: base, label: t("dashboard"), icon: LayoutDashboard },
    { href: `${base}/courses`, label: "Courses", icon: GraduationCap },
    { href: `${base}/curricula`, label: t("curricula"), icon: Library },
    ...(isEditor
      ? [{ href: `${base}/qbank`, label: "Question Banks", icon: ClipboardList }]
      : []),
    { href: `${base}/codes`, label: t("codes"), icon: QrCode },
    { href: `${base}/reports`, label: t("reports"), icon: BarChart3 },
    { href: `${base}/members`, label: t("members"), icon: Users },
  ];

  return (
    <nav className="border-b bg-white px-4 overflow-x-auto">
      <div className="flex gap-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive =
            pathname === tab.href ||
            (tab.href !== base && pathname.startsWith(tab.href));
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`flex items-center gap-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                isActive
                  ? "border-green-600 text-green-700"
                  : "border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300"
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
