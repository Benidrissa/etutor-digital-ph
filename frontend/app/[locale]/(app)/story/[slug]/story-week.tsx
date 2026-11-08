/**
 * Loads one week and hands it to the player.
 *
 * The week is cached in localStorage once fetched, so reopening it works with
 * no network. The platform targets 2G/3G phones, and a week is a single
 * self-contained document, which makes it the natural unit to keep offline.
 */

"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { StoryPlayer } from "@/components/story/story-player";
import { getStoryCourse } from "@/lib/story-course/api";
import type { StoryCourse } from "@/lib/story-course/types";

const cacheKey = (slug: string) => `story-course:${slug}`;

function readCache(slug: string): StoryCourse | null {
  try {
    const raw = window.localStorage.getItem(cacheKey(slug));
    return raw ? (JSON.parse(raw) as StoryCourse) : null;
  } catch {
    // Private mode, blocked storage or corrupt JSON — just fetch instead.
    return null;
  }
}

function writeCache(slug: string, course: StoryCourse): void {
  try {
    window.localStorage.setItem(cacheKey(slug), JSON.stringify(course));
  } catch {
    // Quota or blocked storage: the player works fine without the cache.
  }
}

export function StoryWeek({ slug }: { slug: string }) {
  const t = useTranslations("Story");
  const [course, setCourse] = useState<StoryCourse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;

    /**
     * localStorage is a browser-only store, so it is read on mount rather than
     * during render: a lazy `useState` initializer would return null on the
     * server and the cached week on the client, which is a hydration mismatch.
     * Showing the cached copy first and refreshing behind it is the point —
     * reopening a week has to work with no network.
     */
    const load = async () => {
      const cached = readCache(slug);
      if (cached && active) setCourse(cached);
      try {
        const fresh = await getStoryCourse(slug);
        if (!active) return;
        setCourse(fresh);
        writeCache(slug, fresh);
      } catch {
        if (active && !cached) setFailed(true);
      }
    };
    void load();

    return () => {
      active = false;
    };
  }, [slug]);

  if (failed) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-8">
        <p className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-800">
          {t("loadFailed")}
        </p>
      </main>
    );
  }

  if (!course) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-8" aria-busy="true">
        <div className="h-8 w-2/3 animate-pulse rounded bg-gray-200" />
        <div className="mt-4 space-y-3">
          {[0, 1, 2, 3].map((key) => (
            <div key={key} className="h-16 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      </main>
    );
  }

  return <StoryPlayer course={course} />;
}
