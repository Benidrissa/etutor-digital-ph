"use client";

import { useTranslations } from "next-intl";

import { ballAt, formatNumber, numberLineLast, numberLineModel } from "@/lib/story-course/machines";

import { OUTLINE, useMachineStep, type MachineProps } from "./machine";

const W = 300;
const PAD = 22;

/**
 * A ball rolls along a number line from `from` to `mark` (#2740). Where it is
 * at each step comes from `ballAt`; the ends and the mark are named parts.
 */
export default function NumberLine({ params, lang, play, reveal, reduced }: MachineProps) {
  const t = useTranslations("Story");
  const model = numberLineModel(params);
  const last = model ? numberLineLast(model) : 0;
  const { step, next } = useMachineStep(last, { play, reveal, reduced });
  if (!model) return null;
  const { from, to, mark, ticks } = model;
  const at = (value: number) => PAD + ((value - from) / (to - from)) * (W - 2 * PAD);
  // About six labels, never on top of the ends or the mark.
  const every = Math.ceil(ticks.length / 6);
  const near = (x: number, other: number) => Math.abs(x - other) < 26;
  const labelled = (value: number, i: number) =>
    i % every === 0 && !near(at(value), at(from)) && !near(at(value), at(to)) && !(mark !== null && near(at(value), at(mark)));
  const label = (value: number, y = 76) => (
    <text x={at(value)} y={y} textAnchor="middle" fontSize="10" className="fill-gray-600">
      {formatNumber(value, lang)}
    </text>
  );
  const ring = (part: string, value: number) =>
    model.highlight === part ? (
      <rect x={at(value) - 18} y="22" width="36" height="62" rx="8" fill="none" stroke={OUTLINE} strokeWidth="3" />
    ) : null;
  const mark_ = (part: string, value: number) => (
    <g data-part={part} data-highlighted={model.highlight === part ? "true" : undefined}>
      {ring(part, value)}
      <line x1={at(value)} x2={at(value)} y1="44" y2="62" strokeWidth="3" className="stroke-teal-700" />
      {label(value)}
    </g>
  );
  return (
    <div>
      <svg viewBox={`0 0 ${W} 92`} className="mx-auto block w-full max-w-lg" aria-hidden="true">
        <line x1={PAD} x2={W - PAD} y1="53" y2="53" strokeWidth="2" className="stroke-gray-400" />
        {ticks.map((value, i) => (
          <g key={value}>
            <line x1={at(value)} x2={at(value)} y1="48" y2="58" strokeWidth="1.5" className="stroke-gray-400" />
            {labelled(value, i) ? label(value) : null}
          </g>
        ))}
        {mark_("from", from)}
        {mark_("to", to)}
        {mark !== null ? (
          <g data-part="mark" data-highlighted={model.highlight === "mark" ? "true" : undefined}>
            {ring("mark", mark)}
            <path d={`M${at(mark) - 6} 64 L${at(mark) + 6} 64 L${at(mark)} 56 Z`} className="fill-amber-400" />
            {label(mark, 86)}
          </g>
        ) : null}
        <g
          data-ball={ballAt(model, step)}
          style={{
            transform: `translateX(${at(ballAt(model, step))}px)`,
            transition: reduced ? "none" : "transform 0.6s ease-in-out",
          }}
        >
          <circle cx="0" cy="38" r="9" className="fill-teal-500 stroke-teal-700" strokeWidth="1.5" />
        </g>
      </svg>
      {reduced && step < last && !reveal ? (
        <button
          type="button"
          onClick={next}
          className="mx-auto mt-2 block min-h-11 min-w-11 rounded-lg bg-teal-600 px-5 font-semibold text-white hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {t("machineNext")}
        </button>
      ) : null}
    </div>
  );
}
