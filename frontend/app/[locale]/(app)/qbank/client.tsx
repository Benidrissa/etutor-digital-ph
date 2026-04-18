"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2, Globe, Building2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  listAccessibleQBankBanks,
  type QBankBank,
  type QBankStatus,
  type QBankType,
} from "@/lib/api";

const TYPE_KEY: Record<QBankType, string> = {
  driving: "typeDriving",
  exam_prep: "typeExamPrep",
  psychotechnic: "typePsychotechnic",
  general_culture: "typeGeneralCulture",
};

const STATUS_STYLES: Record<QBankStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  published: "bg-green-100 text-green-700",
  archived: "bg-yellow-100 text-yellow-700",
};

export function QBankAccessibleListClient() {
  const t = useTranslations("qbank");
  const locale = useLocale();
  const [banks, setBanks] = useState<QBankBank[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<QBankType | "all">("all");
  const [visibilityFilter, setVisibilityFilter] = useState<"all" | "public" | "org_only">("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listAccessibleQBankBanks();
        if (!cancelled) setBanks(res);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const filtered = banks.filter((b) => {
    if (typeFilter !== "all" && b.bank_type !== typeFilter) return false;
    if (visibilityFilter !== "all" && b.visibility !== visibilityFilter) return false;
    return true;
  });

  if (banks.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("noAccessible")}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as QBankType | "all")}
          className="rounded-md border bg-background px-3 py-2 text-sm min-h-11"
          aria-label={t("allTypes")}
        >
          <option value="all">{t("allTypes")}</option>
          {(Object.keys(TYPE_KEY) as QBankType[]).map((type) => (
            <option key={type} value={type}>
              {t(TYPE_KEY[type])}
            </option>
          ))}
        </select>
        <select
          value={visibilityFilter}
          onChange={(e) => setVisibilityFilter(e.target.value as "all" | "public" | "org_only")}
          className="rounded-md border bg-background px-3 py-2 text-sm min-h-11"
          aria-label="Visibility"
        >
          <option value="all">{t("allTypes")}</option>
          <option value="public">{t("visibilityPublic")}</option>
          <option value="org_only">{t("visibilityOrgOnly")}</option>
        </select>
      </div>

      <ul className="grid gap-3 md:grid-cols-2">
        {filtered.map((bank) => (
          <li
            key={bank.id}
            className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <h2 className="truncate font-medium">{bank.title}</h2>
                {bank.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {bank.description}
                  </p>
                )}
              </div>
              <Badge className={STATUS_STYLES[bank.status]}>{bank.status}</Badge>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>{t(TYPE_KEY[bank.bank_type])}</span>
              <span aria-hidden="true">·</span>
              <span className="uppercase">{bank.language}</span>
              <span aria-hidden="true">·</span>
              <span>{t("questionCount", { count: bank.question_count })}</span>
              <span aria-hidden="true">·</span>
              <span>{t("testCount", { count: bank.test_count })}</span>
              <span aria-hidden="true">·</span>
              {bank.visibility === "public" ? (
                <span className="inline-flex items-center gap-1">
                  <Globe className="h-3 w-3" aria-hidden="true" /> {t("visibilityPublic")}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <Building2 className="h-3 w-3" aria-hidden="true" /> {t("visibilityOrgOnly")}
                </span>
              )}
            </div>
            <div className="mt-3">
              <Link
                href={`/${locale}/qbank/tests?bank=${bank.id}`}
                className="inline-flex min-h-11 items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                {t("openBankAction")}
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
