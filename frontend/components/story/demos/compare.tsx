"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { pick, type DemoProps } from "./shared";

/**
 * Two things, two numbers (#2711). The learner presses Measure; the bars grow
 * to their values and the verdict is read from the numbers (`equal` is the
 * data's, not a picture's). `scale` is a ruler, plain bars or a score.
 */
export default function Compare({ params, lang, onDone }: DemoProps) {
  const t = useTranslations("Story");
  const [measured, setMeasured] = useState(false);
  const values = (Array.isArray(params.values) ? params.values : [0, 0]).map(Number);
  const labels = [0, 1].map((i) => pick((params.labels as unknown[])?.[i], lang));
  const unit = typeof params.unit === "string" ? ` ${params.unit}` : "";
  const scale = params.scale === "ruler" || params.scale === "score" ? params.scale : "bars";
  const top = Math.max(...values, 1);
  const equal = values[0] === values[1];
  const bigger = values[0] > values[1] ? 0 : 1;

  const measure = () => {
    setMeasured(true);
    onDone?.({ correct: true });
  };

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {labels.map((label, i) => (
          <li key={i}>
            <p className="text-sm font-semibold text-gray-800">
              {label}
              {measured ? <span className="ml-2 font-mono">{`${values[i]}${unit}`}</span> : null}
            </p>
            {scale === "score" ? (
              <p aria-hidden="true" className="text-3xl font-extrabold text-teal-700">
                {measured ? values[i] : "?"}
              </p>
            ) : (
              <div
                aria-hidden="true"
                className={`h-6 rounded bg-gray-100 ${scale === "ruler" ? "border-b-2 border-gray-500" : ""}`}
              >
                <div
                  className="h-6 rounded bg-teal-500 transition-[width] duration-700 motion-reduce:transition-none"
                  style={{ width: measured ? `${(values[i] / top) * 100}%` : "0%" }}
                />
              </div>
            )}
          </li>
        ))}
      </ul>
      {measured ? null : (
        <button
          type="button"
          onClick={measure}
          className="min-h-11 min-w-11 rounded-lg bg-teal-600 px-5 font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {t("demoMeasure")}
        </button>
      )}
      <p role="status" aria-live="polite" className="min-h-6 font-semibold text-gray-900">
        {measured
          ? equal
            ? t("compareEqual", { a: `${values[0]}${unit}`, b: `${values[1]}${unit}` })
            : t("compareBigger", { winner: labels[bigger], a: `${values[0]}${unit}`, b: `${values[1]}${unit}` })
          : ""}
      </p>
    </div>
  );
}
