"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ClipboardList, Loader2, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useOrg } from "@/components/org/org-context";
import { useCurrentUser } from "@/lib/hooks/use-current-user";
import { canEditBank, type OrgRole } from "@/lib/permissions";
import { listQBankBanks, type QBankBank, type QBankStatus, type QBankType } from "@/lib/api";

const TYPE_KEY: Record<QBankType, string> = {
  driving: "typeDriving",
  exam_prep: "typeExamPrep",
  psychotechnic: "typePsychotechnic",
  general_culture: "typeGeneralCulture",
};

const STATUS_KEY: Record<QBankStatus, string> = {
  draft: "statusDraft",
  published: "statusPublished",
  archived: "statusArchived",
};

const STATUS_STYLES: Record<QBankStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  published: "bg-green-100 text-green-700",
  archived: "bg-yellow-100 text-yellow-700",
};

export function QBankListClient() {
  const locale = useLocale();
  const t = useTranslations("qbank");
  const { org, role, loading: orgLoading } = useOrg();
  const currentUser = useCurrentUser();
  const isEditor = canEditBank(role as OrgRole, currentUser?.role);
  const [banks, setBanks] = useState<QBankBank[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<QBankType | "all">("all");

  useEffect(() => {
    if (!org) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await listQBankBanks(org.id);
        if (!cancelled) setBanks(res);
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [org]);

  if (orgLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (!org) {
    return <p className="text-muted-foreground">Organization not found.</p>;
  }

  const filtered = typeFilter === "all" ? banks : banks.filter((b) => b.bank_type === typeFilter);
  const base = `/${locale}/org/${org.slug}/qbank`;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <ClipboardList className="h-6 w-6" /> {t("banksTitle")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("banksSubtitle")}</p>
        </div>
        {isEditor && (
          <Link
            href={`${base}/create`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-2.5 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/80"
          >
            <Plus className="h-4 w-4" /> {t("newBank")}
          </Link>
        )}
      </header>

      <div className="flex flex-wrap gap-2">
        {(["all", ...Object.keys(TYPE_KEY)] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTypeFilter(key as QBankType | "all")}
            className={`rounded-full px-3 py-1 text-sm ${
              typeFilter === key
                ? "bg-green-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {key === "all" ? t("allTypes") : t(TYPE_KEY[key as QBankType])}
          </button>
        ))}
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <p className="text-sm text-muted-foreground">{t("noBanks")}</p>
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((bank) => (
            <li key={bank.id}>
              <Link
                href={`${base}/${bank.id}`}
                className="flex h-full flex-col gap-3 rounded-lg border bg-white p-4 transition hover:border-green-500 hover:shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-medium">{bank.title}</h2>
                  <Badge className={STATUS_STYLES[bank.status]}>
                    {t(STATUS_KEY[bank.status])}
                  </Badge>
                </div>
                {bank.description && (
                  <p className="line-clamp-2 text-sm text-muted-foreground">{bank.description}</p>
                )}
                <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>{t(TYPE_KEY[bank.bank_type])}</span>
                  <span>{t("questionCount", { count: bank.question_count })}</span>
                  <span>{t("testCount", { count: bank.test_count })}</span>
                  <span>{t("timePerQSuffix", { seconds: bank.time_per_question_sec })}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
