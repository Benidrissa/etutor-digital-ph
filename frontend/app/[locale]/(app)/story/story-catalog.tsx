/**
 * The weeks the app lists (format A.1 `catalog.json`).
 *
 * Weeks are small rows, so the whole catalog is one request; the week itself
 * is only fetched when she opens it.
 */

"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { text } from "@/lib/story-course/answer";
import { listStoryCourses } from "@/lib/story-course/api";
import type { StoryCourseListItem } from "@/lib/story-course/types";

export function StoryCatalog() {
  const t = useTranslations("Story");
  const locale = useLocale();
  const [items, setItems] = useState<StoryCourseListItem[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    listStoryCourses({ limit: 50 })
      .then((data) => {
        if (active) setItems(data.items);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  if (failed) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-8">
        <p className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-800">
          {t("loadFailed")}
        </p>
      </main>
    );
  }

  if (items === null) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-8">
        <ul className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((key) => (
            <li key={key} className="h-24 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </ul>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900">{t("catalogTitle")}</h1>
      <p className="mt-1 text-gray-600">{t("catalogDescription")}</p>

      {items.length === 0 ? (
        <p className="mt-6 rounded-lg border border-dashed border-gray-300 p-6 text-center text-gray-500">
          {t("empty")}
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/${locale}/story/${item.id}`}
                className="block min-h-11 rounded-xl border border-gray-200 bg-white p-4 transition hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
              >
                <p className="text-xs uppercase tracking-wide text-gray-500">
                  {[item.course, item.unit, t("week", { week: item.week })]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                <p className="mt-1 font-bold text-gray-900">
                  {text(item.title, locale, item.languages?.target ?? "en")}
                </p>
                <p className="mt-2 text-sm text-gray-600">
                  {t("counts", {
                    questions: item.question_count,
                    exercises: item.exercise_count,
                    points: item.max_points,
                  })}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
