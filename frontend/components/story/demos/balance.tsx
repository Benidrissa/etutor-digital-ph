"use client";

import { useTranslations } from "next-intl";

import { beamAngle, balanceLast, balanceModel, formatNumber, wrapLabel, type BalanceModel } from "@/lib/story-course/machines";

import { pick } from "./shared";
import { OUTLINE, useMachineStep, type MachineProps } from "./machine";

const CX = 150;
const TOP = 30;
const HALF = 90;
const LINE = 11;

/**
 * A two-pan balance (#2756). The beam's angle at each step comes from
 * `beamAngle`, read from the two values: level when they are equal. The pans
 * turn against the beam so they hang upright.
 */
export default function Balance({ params, lang, play, reveal, reduced }: MachineProps) {
  const t = useTranslations("Story");
  const model = balanceModel(params);
  const last = model ? balanceLast(model) : 0;
  const { step, next } = useMachineStep(last, { play, reveal, reduced });
  if (!model) return null;
  const angle = beamAngle(model, step);
  const move = reduced ? "none" : "transform 0.8s ease-in-out";
  const pan = (part: "left" | "right", side: BalanceModel["left"], x: number) => {
    const lines = wrapLabel(pick(side.label, lang), 14).slice(0, 6);
    const marked = model.highlight === part;
    return (
      <g data-part={part} data-highlighted={marked ? "true" : undefined} style={{ transform: `translate(${x}px, 0px) rotate(${-angle}deg)`, transition: move }}>
        {marked ? <rect x="-48" y="-8" width="96" height={72 + LINE * lines.length} rx="8" fill="none" stroke={OUTLINE} strokeWidth="3" /> : null}
        <path d="M0 0 L-32 40 M0 0 L32 40" strokeWidth="1.5" className="stroke-gray-400" />
        <rect x="-38" y="40" width="76" height="6" rx="3" className="fill-gray-400" />
        <text y="34" textAnchor="middle" fontSize="13" className="fill-teal-700 font-semibold">
          {formatNumber(side.value, lang)}
        </text>
        <text y="58" textAnchor="middle" fontSize="10" className="fill-gray-600">
          {lines.map((line, i) => (
            <tspan key={i} x="0" dy={i === 0 ? 0 : LINE}>
              {line}
            </tspan>
          ))}
        </text>
      </g>
    );
  };
  return (
    <div>
      <svg viewBox="0 0 300 190" className="mx-auto block w-full max-w-lg" aria-hidden="true">
        <path d={`M${CX} ${TOP} L${CX - 14} 172 L${CX + 14} 172 Z`} className="fill-gray-200" />
        <g data-angle={angle} style={{ transform: `translate(${CX}px, ${TOP}px) rotate(${angle}deg)`, transition: move }}>
          <g data-part="beam" data-highlighted={model.highlight === "beam" ? "true" : undefined}>
            {model.highlight === "beam" ? <rect x={-HALF - 8} y="-11" width={2 * HALF + 16} height="22" rx="8" fill="none" stroke={OUTLINE} strokeWidth="3" /> : null}
            <rect x={-HALF} y="-3" width={2 * HALF} height="6" rx="3" className="fill-teal-700" />
            <circle r="6" className="fill-amber-400" />
          </g>
          {pan("left", model.left, -HALF)}
          {pan("right", model.right, HALF)}
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
