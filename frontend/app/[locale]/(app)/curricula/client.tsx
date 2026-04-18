"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import Image from "next/image";
import { getCurricula, type CurriculumPublicResponse } from "@/lib/api";

export function CurriculaTopLevelClient() {
  const locale = useLocale();
  const t = useTranslations("qbank");
  const [curricula, setCurricula] = useState<CurriculumPublicResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getCurricula();
        if (!cancelled) setCurricula(res);
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
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (curricula.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("noCurricula")}</p>;
  }

  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {curricula.map((c) => {
        const title = locale === "fr" ? c.title_fr : c.title_en;
        const description = locale === "fr" ? c.description_fr : c.description_en;
        return (
          <li
            key={c.id}
            className="overflow-hidden rounded-lg border bg-card transition-shadow hover:shadow-md"
          >
            {c.cover_image_url && (
              <div className="relative h-32 w-full">
                <Image src={c.cover_image_url} alt="" fill className="object-cover" />
              </div>
            )}
            <div className="space-y-2 p-4">
              <h2 className="truncate font-medium">{title}</h2>
              {description && (
                <p className="line-clamp-2 text-xs text-muted-foreground">{description}</p>
              )}
              <p className="text-xs text-muted-foreground">
                {t("courseCountShort", { count: c.course_count })}
              </p>
              <Link
                href={`/${locale}/curricula/${c.slug}`}
                className="inline-flex min-h-11 items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                {t("openAction")}
              </Link>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
