"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { fetchMyOrganizations } from "@/lib/api";
import type { OrgWithRole } from "@/lib/api";
import { Building2, Plus, Users, ChevronRight } from "lucide-react";

export default function OrganizationsPage() {
  const t = useTranslations("Organization");
  const locale = useLocale();
  const [orgs, setOrgs] = useState<OrgWithRole[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMyOrganizations()
      .then(setOrgs)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("title")}</h1>
        </div>
        <Link
          href={`/${locale}/organizations/create`}
          className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
        >
          <Plus className="h-4 w-4" />
          {t("createOrg")}
        </Link>
      </div>

      {orgs.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center">
          <Building2 className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-600 font-medium">{t("noOrgs")}</p>
          <Link
            href={`/${locale}/organizations/create`}
            className="inline-flex items-center gap-2 mt-4 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
          >
            <Plus className="h-4 w-4" />
            {t("createOrg")}
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {orgs.map((m) => (
            <Link
              key={m.organization.id}
              href={`/${locale}/org/${m.organization.slug}`}
              className="flex items-center justify-between rounded-lg border bg-white p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center gap-4">
                {m.organization.logo_url ? (
                  <img
                    src={m.organization.logo_url}
                    alt={m.organization.name}
                    className="h-10 w-10 rounded-lg object-cover"
                  />
                ) : (
                  <div className="h-10 w-10 rounded-lg bg-green-100 flex items-center justify-center">
                    <Building2 className="h-5 w-5 text-green-600" />
                  </div>
                )}
                <div>
                  <p className="font-medium">{m.organization.name}</p>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 font-medium">
                      <Users className="h-3 w-3" />
                      {t(m.role as "owner" | "admin" | "viewer")}
                    </span>
                    {m.organization.contact_email && (
                      <span>{m.organization.contact_email}</span>
                    )}
                  </div>
                </div>
              </div>
              <ChevronRight className="h-5 w-5 text-gray-400" />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
