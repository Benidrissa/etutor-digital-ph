"use client";

import { useEffect, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { useOrg } from "@/components/org/org-context";
import { fetchOrgQBanks } from "@/lib/api";
import type { QBankResponse, QBankStatus } from "@/lib/api";
import { Plus, BookOpen, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STATUS_COLORS: Record<QBankStatus, string> = {
  draft: "bg-stone-100 text-stone-600",
  published: "bg-green-100 text-green-700",
  archived: "bg-amber-100 text-amber-700",
};

export default function OrgQBankListPage() {
  const t = useTranslations("QBank");
  const locale = useLocale();
  const { org, orgId } = useOrg();
  const [banks, setBanks] = useState<QBankResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState<string>("");

  useEffect(() => {
    if (!orgId) return;
    fetchOrgQBanks(orgId)
      .then(setBanks)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [orgId]);

  if (!org) return null;

  const bankTypes = Array.from(new Set(banks.map((b) => b.bank_type))).filter(Boolean);

  const filtered = filterType
    ? banks.filter((b) => b.bank_type === filterType)
    : banks;

  const base = `/${locale}/org/${org.slug}/qbank`;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-stone-900">{t("questionBanks")}</h1>
        <Button
          asChild
          className="min-h-11 bg-teal-600 hover:bg-teal-700 shrink-0"
        >
          <Link href={`${base}/create`}>
            <Plus className="mr-2 h-4 w-4" />
            {t("createBank")}
          </Link>
        </Button>
      </div>

      {bankTypes.length > 0 && (
        <div className="flex items-center gap-3">
          <Select
            value={filterType || "all"}
            onValueChange={(v) => setFilterType(v === "all" ? "" : v)}
          >
            <SelectTrigger className="w-48">
              <SelectValue placeholder={t("allTypes")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allTypes")}</SelectItem>
              {bankTypes.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-stone-500">
            {t("bankCount", { count: filtered.length })}
          </span>
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center">
          <BookOpen className="h-12 w-12 text-stone-300 mx-auto mb-4" />
          <p className="font-medium text-stone-600">{t("noBanks")}</p>
          <p className="mt-1 text-sm text-stone-400">{t("noBanksDesc")}</p>
          <Button asChild className="mt-4 min-h-11 bg-teal-600 hover:bg-teal-700">
            <Link href={`${base}/create`}>
              <Plus className="mr-2 h-4 w-4" />
              {t("createBank")}
            </Link>
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((bank) => (
            <Link
              key={bank.id}
              href={`${base}/${bank.id}`}
              className="flex items-center justify-between rounded-lg border bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="rounded-lg bg-teal-50 p-2 shrink-0">
                  <BookOpen className="h-5 w-5 text-teal-600" />
                </div>
                <div className="min-w-0">
                  <p className="font-medium text-stone-900 truncate">{bank.title}</p>
                  <p className="text-xs text-stone-500 mt-0.5">
                    {bank.bank_type} ·{" "}
                    {t("questionsCount", { count: bank.question_count })} ·{" "}
                    {bank.language.toUpperCase()}
                  </p>
                </div>
              </div>
              <span
                className={`ml-4 inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  STATUS_COLORS[bank.status]
                }`}
              >
                {t(`status${bank.status.charAt(0).toUpperCase() + bank.status.slice(1)}`)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
