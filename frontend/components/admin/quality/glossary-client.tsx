"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type GlossaryEntryResponse, getCourseGlossary } from "@/lib/api-quality";

type Language = "fr" | "en";

const CONSISTENCY_VARIANT: Record<
  GlossaryEntryResponse["consistency_status"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  consistent: "default",
  drift_detected: "destructive",
  unsourced: "secondary",
};

export function GlossaryClient({ courseId }: { courseId: string }) {
  const t = useTranslations("Admin.qualityAgent.glossary");
  const tConsistency = useTranslations("Admin.qualityAgent.glossary.consistency");
  const [language, setLanguage] = useState<Language>("fr");

  const glossaryQ = useQuery<GlossaryEntryResponse[]>({
    queryKey: ["admin", "quality", courseId, "glossary", language],
    queryFn: () => getCourseGlossary(courseId, language),
  });

  const entries = glossaryQ.data ?? [];
  const driftCount = entries.filter((e) => e.consistency_status === "drift_detected").length;

  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-col gap-2">
        <Link
          href={`/admin/courses/${courseId}/quality`}
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("backToCourseQuality")}
        </Link>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t("language")}:</span>
          <div className="inline-flex rounded-md border" role="group" aria-label={t("language")}>
            {(["fr", "en"] as Language[]).map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => setLanguage(lang)}
                aria-pressed={language === lang}
                className={cn(
                  "px-3 py-1 text-sm font-medium first:rounded-l-md last:rounded-r-md",
                  language === lang
                    ? "bg-primary text-primary-foreground"
                    : "bg-background text-muted-foreground hover:bg-muted",
                )}
              >
                {lang.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {driftCount > 0 && (
          <div className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertTriangle className="size-3" aria-hidden="true" />
            {t("driftSummary", { count: driftCount })}
          </div>
        )}
      </div>

      {glossaryQ.isLoading && (
        <p className="py-12 text-center text-sm text-muted-foreground">{t("loading")}</p>
      )}

      {glossaryQ.error && (
        <p className="py-12 text-center text-sm text-destructive" role="alert">
          {glossaryQ.error instanceof Error ? glossaryQ.error.message : t("error")}
        </p>
      )}

      {!glossaryQ.isLoading && !glossaryQ.error && entries.length === 0 && (
        <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
          {t("empty")}
        </div>
      )}

      {!glossaryQ.isLoading && !glossaryQ.error && entries.length > 0 && (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-left text-muted-foreground">
                <th className="px-3 py-2">{t("col.term")}</th>
                <th className="px-3 py-2">{t("col.definition")}</th>
                <th className="px-3 py-2">{t("col.firstUnit")}</th>
                <th className="px-3 py-2">{t("col.occurrences")}</th>
                <th className="px-3 py-2">{t("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const isDrift = e.consistency_status === "drift_detected";
                return (
                  <tr
                    key={e.id}
                    className={cn(
                      "border-b last:border-0 align-top",
                      isDrift
                        ? "bg-amber-50/60 hover:bg-amber-100/60 dark:bg-amber-950/20"
                        : "hover:bg-muted/20",
                    )}
                  >
                    <td className="px-3 py-2 font-medium">{e.term_display}</td>
                    <td className="px-3 py-2 max-w-md">
                      <div className="text-sm">{e.canonical_definition}</div>
                      {e.drift_details && (
                        <div className="mt-1 text-xs text-amber-800 dark:text-amber-300">
                          <span className="font-medium">{t("driftDetailsLabel")}:</span>{" "}
                          {e.drift_details}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                      {e.first_unit_number ?? "—"}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">
                      {e.occurrences_count}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={CONSISTENCY_VARIANT[e.consistency_status]}>
                        {tConsistency(e.consistency_status)}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
