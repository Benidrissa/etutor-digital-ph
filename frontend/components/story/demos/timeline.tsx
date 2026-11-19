"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { list, pick, type DemoProps } from "./shared";

/**
 * Put the events in order (#2711). The learner taps them from first to last
 * (a tap alternative to dragging, with the keyboard too); the order is read
 * from each event's `at`, in the data.
 */
export default function Timeline({ params, lang, onDone }: DemoProps) {
  const t = useTranslations("Story");
  const events = list(params.events).map((event, index) => {
    const row = (event ?? {}) as { label?: unknown; at?: unknown };
    return { index, label: pick(row.label, lang), at: Number(row.at) };
  });
  const [order, setOrder] = useState<number[]>([]);
  const truth = [...events].sort((a, b) => a.at - b.at).map((e) => e.index);
  const done = order.length === events.length && events.length > 0;
  const correct = done && order.every((n, i) => n === truth[i]);
  // Shown in the order given, turned round so it is not already the answer.
  const shown = [...events].reverse();

  const tap = (n: number) => {
    if (done || order.includes(n)) return;
    const next = [...order, n];
    setOrder(next);
    if (next.length === events.length) onDone?.({ correct: next.every((m, i) => m === truth[i]) });
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-700">{t("timelineInstruction")}</p>
      <ul className="space-y-2">
        {shown.map((event) => {
          const place = order.indexOf(event.index);
          return (
            <li key={event.index}>
              <button
                type="button"
                disabled={place >= 0 || done}
                onClick={() => tap(event.index)}
                className="flex min-h-11 w-full items-center gap-3 rounded-lg border border-gray-300 bg-white px-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:bg-gray-50"
              >
                <span aria-hidden="true" className="flex h-7 w-7 items-center justify-center rounded-full bg-teal-600 text-sm font-bold text-white">
                  {place >= 0 ? place + 1 : ""}
                </span>
                <span>{event.label}</span>
                {place >= 0 ? <span className="sr-only">{t("timelinePlace", { n: place + 1 })}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
      {order.length > 0 && !done ? (
        <button
          type="button"
          onClick={() => setOrder([])}
          className="min-h-11 rounded-lg border border-gray-300 px-4 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {t("timelineReset")}
        </button>
      ) : null}
      <p role="status" aria-live="polite" className="min-h-6 font-semibold text-gray-900">
        {done
          ? correct
            ? t("timelineRight")
            : t("timelineWrong", { order: truth.map((n) => events[n].label).join(" → ") })
          : ""}
      </p>
    </div>
  );
}
