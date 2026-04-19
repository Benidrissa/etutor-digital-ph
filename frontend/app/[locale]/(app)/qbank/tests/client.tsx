"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Building2,
  ClipboardList,
  ListChecks,
  Loader2,
  PlayCircle,
  Timer,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { listAccessibleTests, type AccessibleQBankTest } from "@/lib/api";

const MODE_PILL: Record<string, string> = {
  exam: "bg-red-100 text-red-700",
  training: "bg-green-100 text-green-700",
  review: "bg-blue-100 text-blue-700",
};

export function QBankTestsDiscoveryClient() {
  const locale = useLocale();
  const t = useTranslations("qbank");
  const [tests, setTests] = useState<AccessibleQBankTest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAccessibleTests()
      .then((rows) => {
        if (cancelled) return;
        setTests(rows);
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

  // Group by bank so the learner sees which bank each test belongs to.
  const groupedByBank = useMemo(() => {
    const groups: Record<
      string,
      {
        bankId: string;
        bankTitle: string | null;
        bankOrgName: string | null;
        tests: AccessibleQBankTest[];
      }
    > = {};
    for (const test of tests) {
      const key = test.question_bank_id;
      if (!groups[key]) {
        groups[key] = {
          bankId: test.question_bank_id,
          bankTitle: test.bank_title ?? null,
          bankOrgName: test.bank_org_name ?? null,
          tests: [],
        };
      }
      groups[key].tests.push(test);
    }
    return Object.values(groups);
  }, [tests]);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:py-8">
      <header className="mb-6 flex flex-col gap-2 sm:mb-8">
        <div className="flex items-center gap-2">
          <ListChecks className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-bold sm:text-3xl">
            {t("testsDiscoveryTitle")}
          </h1>
        </div>
        <p className="text-sm text-muted-foreground sm:text-base">
          {t("testsDiscoveryIntro")}
        </p>
      </header>

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

      {!loading && !error && tests.length === 0 && (
        <p className="rounded-lg border border-dashed border-muted-foreground/30 p-8 text-center text-sm text-muted-foreground">
          {t("testsDiscoveryEmpty")}
        </p>
      )}

      {!loading && !error && groupedByBank.length > 0 && (
        <div className="space-y-6">
          {groupedByBank.map((group) => (
            <section key={group.bankId} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <ClipboardList className="h-4 w-4" aria-hidden />
                <span className="text-foreground">
                  {group.bankTitle ?? "—"}
                </span>
                {group.bankOrgName && (
                  <span className="flex items-center gap-1">
                    <Building2 className="h-3.5 w-3.5" aria-hidden />
                    {group.bankOrgName}
                  </span>
                )}
              </div>
              <ul className="grid gap-3 sm:grid-cols-2">
                {group.tests.map((test) => (
                  <li key={test.id}>
                    <Link
                      href={`/${locale}/qbank/tests/${test.id}`}
                      className="flex h-full flex-col gap-2 rounded-lg border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-muted/50"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h2 className="text-base font-semibold leading-snug">
                          {test.title}
                        </h2>
                        <Badge
                          className={`${MODE_PILL[test.mode] ?? "bg-muted text-muted-foreground"} shrink-0`}
                          variant="secondary"
                        >
                          {t(`mode.${test.mode}`)}
                        </Badge>
                      </div>
                      <div className="mt-auto flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                        {typeof test.question_count === "number" && (
                          <span className="flex items-center gap-1">
                            <ClipboardList
                              className="h-3.5 w-3.5"
                              aria-hidden
                            />
                            {t("questionCount", { count: test.question_count })}
                          </span>
                        )}
                        {typeof test.time_per_question_sec === "number" && (
                          <span className="flex items-center gap-1">
                            <Timer className="h-3.5 w-3.5" aria-hidden />
                            {test.time_per_question_sec}s / {t("perQuestion")}
                          </span>
                        )}
                        <span className="ml-auto flex items-center gap-1 text-primary">
                          <PlayCircle className="h-4 w-4" aria-hidden />
                          {t("startTest")}
                        </span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
