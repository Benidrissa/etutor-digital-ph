/**
 * The picture a question or a paper task is about (#2711), as a thumbnail the
 * learner can still see while they answer. Its alternative text is the
 * figure's own `alt_text_fr` / `alt_text_en`; a picture that fails to load
 * leaves nothing behind (the question never depends on it being there).
 */

"use client";

import { useState } from "react";

import { API_BASE } from "@/lib/api";
import { figureUrl } from "@/lib/story-course/media";
import type { Stimulus } from "@/lib/story-course/types";

export function StimulusThumb({ stimulus, lang }: { stimulus?: Stimulus; lang: "fr" | "en" }) {
  const [failed, setFailed] = useState(false);
  const url = figureUrl(stimulus, lang);
  if (!stimulus || !url || failed) return null;
  const alt = stimulus.alt?.[lang] ?? stimulus.alt?.[lang === "fr" ? "en" : "fr"] ?? "";
  return (
    <figure className="mb-2 flex justify-center" data-stimulus="">
      {/* eslint-disable-next-line @next/next/no-img-element -- same-origin, cached by the service worker */}
      <img
        src={`${API_BASE}${url}`}
        alt={alt}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="h-auto max-h-28 w-auto max-w-[60%] rounded-md border border-gray-200 object-contain"
      />
    </figure>
  );
}
