"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { list, pick, type DemoProps } from "./shared";

/**
 * Sort before the explanation (#2711). Dragging is not needed and not offered:
 * each item has one button per box (44 px, Tab, Enter), which also works with
 * a screen reader. Check compares with the `bin` of each item, from the data.
 */
export default function Sort({ params, lang, onDone, reveal }: DemoProps) {
  const t = useTranslations("Story");
  const bins = list(params.bins).map((bin) => pick(bin, lang));
  const items = list(params.items).map((item) => {
    const row = (item ?? {}) as { label?: unknown; bin?: unknown };
    return { label: pick(row.label, lang), bin: Number(row.bin) };
  });
  const [placed, setPlaced] = useState<Record<number, number>>({});
  const [done, setChecked] = useState(false);
  const checked = done || !!reveal;
  const all = items.every((_, i) => placed[i] !== undefined);
  const right = items.filter((item, i) => placed[i] === item.bin).length;

  const check = () => {
    setChecked(true);
    onDone?.({ correct: right === items.length });
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-700">{t("sortInstruction")}</p>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i} className="rounded-lg border border-gray-200 p-2">
            <p className="font-semibold text-gray-900">
              {item.label}
              {checked ? (
                <span className="ml-2 text-sm">
                  {placed[i] === item.bin ? "✓" : `✗ → ${bins[item.bin - 1] ?? ""}`}
                </span>
              ) : null}
            </p>
            <div role="group" aria-label={item.label} className="mt-1 flex flex-wrap gap-2">
              {bins.map((bin, b) => (
                <button
                  key={b}
                  type="button"
                  disabled={checked}
                  aria-pressed={placed[i] === b + 1}
                  onClick={() => setPlaced((p) => ({ ...p, [i]: b + 1 }))}
                  className={`min-h-11 min-w-11 rounded-lg border px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                    placed[i] === b + 1 ? "border-teal-600 bg-teal-50 font-semibold" : "border-gray-300 bg-white"
                  }`}
                >
                  {bin}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {checked ? null : (
        <button
          type="button"
          disabled={!all}
          onClick={check}
          className="min-h-11 rounded-lg bg-teal-600 px-5 font-semibold text-white disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {t("check")}
        </button>
      )}
      <p role="status" aria-live="polite" className="min-h-6 font-semibold text-gray-900">
        {checked ? t("sortResult", { right, total: items.length }) : ""}
      </p>
    </div>
  );
}
