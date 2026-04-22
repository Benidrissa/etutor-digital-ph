"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Brain, Building2, ClipboardList, Globe, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  listAccessibleQBanks,
  type QBankBank,
  type QBankType,
} from "@/lib/api";

const TYPE_KEY: Record<QBankType, string> = {
  driving: "typeDriving",
  exam_prep: "typeExamPrep",
  psychotechnic: "typePsychotechnic",
  general_culture: "typeGeneralCulture",
};

const PILL_COLORS: Record<QBankType, string> = {
  driving: "bg-blue-100 text-blue-700",
  exam_prep: "bg-indigo-100 text-indigo-700",
  psychotechnic: "bg-purple-100 text-purple-700",
  general_culture: "bg-amber-100 text-amber-700",
};

export function QBankDiscoveryClient() {
  const locale = useLocale();
  const t = useTranslations("qbank");
  const tNav = useTranslations("Navigation");
  const [banks, setBanks] = useState<QBankBank[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<QBankType | "all">("all");

  useEffect(() => {
    let cancelled = false;
    listAccessibleQBanks()
      .then((rows) => {
        if (cancelled) return;
        setBanks(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Load failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (typeFilter === "all") return banks;
    return banks.filter((b) => b.bank_type === typeFilter);
  }, [banks, typeFilter]);

  // Group by organization. Public banks (visibility==="public") go first
  // under a synthetic "__public__" section; org-restricted banks follow,
  // grouped by org alphabetically (#1782).
  const { publicGroup, orgGroups } = useMemo(() => {
    const pub: QBankBank[] = [];
    const orgMap: Record<
      string,
      { orgId: string; orgName: string; orgSlug: string | null; banks: QBankBank[] }
    > = {};
    for (const bank of filtered) {
      if (bank.visibility === "public" || bank.organization_id === null) {
        pub.push(bank);
      } else {
        const key = bank.organization_id;
        if (!orgMap[key]) {
          orgMap[key] = {
            orgId: bank.organization_id,
            orgName: bank.organization_name ?? "—",
            orgSlug: bank.organization_slug ?? null,
            banks: [],
          };
        }
        orgMap[key].banks.push(bank);
      }
    }
    const sorted = Object.values(orgMap).sort((a, b) =>
      a.orgName.localeCompare(b.orgName),
    );
    return { publicGroup: pub, orgGroups: sorted };
  }, [filtered]);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:py-8">
      <header className="mb-6 flex flex-col gap-2 sm:mb-8">
        <div className="flex items-center gap-2">
          <Brain className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-bold sm:text-3xl">{tNav("qbank")}</h1>
        </div>
        <p className="text-sm text-muted-foreground sm:text-base">
          {t("discoveryIntro")}
        </p>
      </header>

      <div className="mb-4 flex flex-wrap gap-2 sm:mb-6">
        <FilterChip
          active={typeFilter === "all"}
          onClick={() => setTypeFilter("all")}
          label={t("filterAllTypes")}
        />
        {(Object.keys(TYPE_KEY) as QBankType[]).map((type) => (
          <FilterChip
            key={type}
            active={typeFilter === type}
            onClick={() => setTypeFilter(type)}
            label={t(TYPE_KEY[type])}
          />
        ))}
      </div>

      {loading && (
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {!loading && error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </p>
      )}

      {!loading && !error && filtered.length === 0 && (
        <p className="rounded-lg border border-dashed border-muted-foreground/30 p-8 text-center text-sm text-muted-foreground">
          {t("discoveryEmpty")}
        </p>
      )}

      {!loading && !error && (publicGroup.length > 0 || orgGroups.length > 0) && (
        <div className="space-y-6">
          {publicGroup.length > 0 && (
            <section className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <Globe className="h-4 w-4" aria-hidden />
                <span>{t("publicSection")}</span>
              </div>
              <BankGrid banks={publicGroup} locale={locale} orgSlug={null} t={t} />
            </section>
          )}
          {orgGroups.map((group) => (
            <section key={group.orgId} className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <Building2 className="h-4 w-4" aria-hidden />
                <span>{group.orgName}</span>
                {group.orgSlug && (
                  <Link
                    href={`/${locale}/org/${group.orgSlug}`}
                    className="text-primary underline-offset-2 hover:underline"
                  >
                    {t("discoveryOrgLink")}
                  </Link>
                )}
              </div>
              <BankGrid banks={group.banks} locale={locale} orgSlug={group.orgSlug} t={t} />
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function BankGrid({
  banks,
  locale,
  orgSlug,
  t,
}: {
  banks: QBankBank[];
  locale: string;
  orgSlug: string | null;
  t: ReturnType<typeof useTranslations<"qbank">>;
}) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {banks.map((bank) => (
        <li key={bank.id}>
          <Link
            href={
              orgSlug
                ? `/${locale}/org/${orgSlug}/qbank/${bank.id}`
                : `/${locale}/qbank/banks/${bank.id}`
            }
            className="flex h-full flex-col gap-2 rounded-lg border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-muted/50"
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-base font-semibold leading-snug">
                {bank.title}
              </h2>
              <Badge
                className={`${PILL_COLORS[bank.bank_type]} shrink-0`}
                variant="secondary"
              >
                {t(TYPE_KEY[bank.bank_type])}
              </Badge>
            </div>
            {bank.description && (
              <p className="line-clamp-2 text-xs text-muted-foreground">
                {bank.description}
              </p>
            )}
            <div className="mt-auto flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <ClipboardList className="h-3.5 w-3.5" aria-hidden />
                {t("questionCount", { count: bank.question_count })}
              </span>
              <span>{t("testCount", { count: bank.test_count })}</span>
              <span>
                {bank.time_per_question_sec}s / {t("perQuestion")}
              </span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "rounded-full border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground sm:text-sm"
          : "rounded-full border border-border bg-background px-3 py-1 text-xs font-medium hover:border-primary/50 sm:text-sm"
      }
    >
      {label}
    </button>
  );
}
