"use client";

import { useTranslations } from "next-intl";

import { cycleLast, cycleModel, markerAt, wrapLabel } from "@/lib/story-course/machines";

import { pick } from "./shared";
import { OUTLINE, useMachineStep, type MachineProps } from "./machine";

const CX = 150;
const CY = 135;
const R = 60;
const LINE = 11;

/**
 * Stages on a ring and a marker that goes once round it from `start` (#2756).
 * Where the marker is at each step comes from `markerAt`.
 */
export default function Cycle({ params, lang, play, reveal, reduced }: MachineProps) {
  const t = useTranslations("Story");
  const model = cycleModel(params);
  const last = model ? cycleLast(model) : 0;
  const { step, next } = useMachineStep(last, { play, reveal, reduced });
  if (!model) return null;
  const count = model.stages.length;
  const angle = (i: number) => -90 + (360 * i) / count;
  const at = (i: number) => [CX + R * Math.cos((angle(i) * Math.PI) / 180), CY + R * Math.sin((angle(i) * Math.PI) / 180)];
  const [mx, my] = at(markerAt(model, step));
  return (
    <div>
      <svg viewBox="0 0 300 270" className="mx-auto block w-full max-w-lg" aria-hidden="true">
        <circle cx={CX} cy={CY} r={R} fill="none" strokeWidth="2" className="stroke-gray-300" />
        {model.stages.map((_, i) => {
          // An arrowhead half way to the next stage, pointing clockwise.
          const [ax, ay] = [CX + R * Math.cos(((angle(i) + 180 / count) * Math.PI) / 180), CY + R * Math.sin(((angle(i) + 180 / count) * Math.PI) / 180)];
          return <path key={i} d="M-4 -4 L4 0 L-4 4 Z" className="fill-gray-400" style={{ transform: `translate(${ax}px, ${ay}px) rotate(${angle(i) + 180 / count + 90}deg)` }} />;
        })}
        <circle data-marker={markerAt(model, step)} r="12" className="fill-amber-400" style={{ transform: `translate(${mx}px, ${my}px)`, transition: reduced ? "none" : "transform 0.6s ease-in-out" }} />
        {model.stages.map((stage, i) => {
          const [x, y] = at(i);
          const cos = Math.cos((angle(i) * Math.PI) / 180);
          const side = cos > 0.3 ? 1 : cos < -0.3 ? -1 : 0;
          const lines = wrapLabel(pick(stage, lang), 11).slice(0, 6);
          const marked = model.highlight === `stage${i + 1}`;
          // Beside the node on the sides, above or below it at the top and bottom.
          const first = side ? y + 3 - ((lines.length - 1) * LINE) / 2 : y < CY ? y - 18 - (lines.length - 1) * LINE : y + 26;
          return (
            <g key={i} data-part={`stage${i + 1}`} data-highlighted={marked ? "true" : undefined}>
              {marked ? <circle cx={x} cy={y} r="19" fill="none" stroke={OUTLINE} strokeWidth="3" /> : null}
              <circle cx={x} cy={y} r="12" fill="none" strokeWidth="2" className="stroke-teal-700" />
              <text x={x} y={y + 4} textAnchor="middle" fontSize="11" className="fill-teal-700 font-semibold">
                {i + 1}
              </text>
              <text textAnchor={side > 0 ? "start" : side < 0 ? "end" : "middle"} fontSize="10" className="fill-gray-600">
                {lines.map((line, k) => (
                  <tspan key={k} x={x + side * 18} y={first + k * LINE}>
                    {line}
                  </tspan>
                ))}
              </text>
            </g>
          );
        })}
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
