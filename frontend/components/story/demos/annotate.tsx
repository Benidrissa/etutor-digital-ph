"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { API_BASE } from "@/lib/api";

import { list, pick, type DemoProps } from "./shared";

/**
 * A figure cut in halves or thirds (#2711): no region detection is needed, so
 * it works while figure vision is off. The learner taps a part; the right one
 * is `expected` in the data. The parts are real buttons (44 px at least, Tab
 * and Enter work); the labels are listed under the figure for a screen reader.
 */
export default function Annotate({ params, lang, onDone }: DemoProps) {
  const t = useTranslations("Story");
  const [picked, setPicked] = useState<number | null>(null);
  const labels = list(params.labels).map((label) => pick(label, lang));
  const expected = Number(params.expected);
  const source = typeof params.source_image_id === "string" ? params.source_image_id : "";
  const generated = typeof params.generated_image_id === "string" ? params.generated_image_id : "";
  const src = source
    ? `${API_BASE}/api/v1/source-images/${source}/data?lang=${lang}`
    : generated
      ? `${API_BASE}/api/v1/images/${generated}/data`
      : "";
  const alt = pick(params.alt, lang);

  const choose = (n: number) => {
    if (picked !== null) return;
    setPicked(n);
    onDone?.({ correct: n === expected });
  };

  return (
    <div className="space-y-2">
      <p className="text-sm text-gray-700">{t("annotateInstruction")}</p>
      <div className="relative mx-auto max-w-md overflow-hidden rounded-lg">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- same-origin, cached by the service worker
          <img src={src} alt={alt} loading="lazy" decoding="async" className="block h-auto w-full" />
        ) : null}
        <div className="absolute inset-0 flex">
          {labels.map((label, i) => {
            const n = i + 1;
            const right = picked !== null && n === expected;
            const wrong = picked === n && n !== expected;
            return (
              <button
                key={n}
                type="button"
                aria-label={t("annotatePart", { n, label })}
                aria-pressed={picked === n}
                disabled={picked !== null}
                onClick={() => choose(n)}
                className={`min-h-11 min-w-11 flex-1 border-2 border-dashed border-white/80 text-sm font-bold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-400 ${
                  right ? "bg-green-500/50" : wrong ? "bg-red-500/40" : "bg-black/10 hover:bg-white/20"
                }`}
              >
                <span className="rounded bg-black/60 px-1">{n}</span>
              </button>
            );
          })}
        </div>
      </div>
      <p role="status" aria-live="polite" className="min-h-6 font-semibold text-gray-900">
        {picked === null
          ? ""
          : picked === expected
            ? t("annotateRight", { label: labels[expected - 1] ?? "" })
            : t("annotateWrong", { label: labels[expected - 1] ?? "" })}
      </p>
    </div>
  );
}
