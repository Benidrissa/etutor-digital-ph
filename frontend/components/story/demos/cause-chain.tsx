"use client";

import { useTranslations } from "next-intl";

import { chainLast, chainModel, linksLit, wrapLabel } from "@/lib/story-course/machines";

import { pick } from "./shared";
import { OUTLINE, useMachineStep, type MachineProps } from "./machine";

const BW = 120;
const BH = 66;
const ROW = 84;
const LINE = 11;

/** An arrow from (x1, y1) to (x2, y2). */
function arrow(x1: number, y1: number, x2: number, y2: number) {
  const len = Math.hypot(x2 - x1, y2 - y1);
  const [ux, uy] = [(x2 - x1) / len, (y2 - y1) / len];
  const [bx, by] = [x2 - 6 * ux, y2 - 6 * uy];
  return `M${x1} ${y1} L${x2} ${y2} M${x2} ${y2} L${bx - 4 * uy} ${by + 4 * ux} M${x2} ${y2} L${bx + 4 * uy} ${by - 4 * ux}`;
}

/**
 * Causes in a row, two to a line and turning at the end of each line so the
 * chain fits 320 px (#2756). The links light up in order: how many are lit at
 * each step comes from `linksLit`.
 */
export default function CauseChain({ params, lang, play, reveal, reduced }: MachineProps) {
  const t = useTranslations("Story");
  const model = chainModel(params);
  const last = model ? chainLast(model) : 0;
  const { step, next } = useMachineStep(last, { play, reveal, reduced });
  if (!model) return null;
  const lit = linksLit(model, step);
  const where = (i: number) => {
    const row = i >> 1;
    return [6 + (row % 2 === 0 ? i % 2 : 1 - (i % 2)) * 168, 3 + row * ROW];
  };
  const rows = ((model.links.length + 1) >> 1);
  const fade = reduced ? "" : "transition-colors duration-500";
  return (
    <div>
      <svg viewBox={`0 0 300 ${rows * ROW - 12}`} className="mx-auto block w-full max-w-lg" aria-hidden="true">
        {model.links.slice(1).map((_, k) => {
          const [x, y] = where(k);
          const [nx, ny] = where(k + 1);
          const d = ny === y ? arrow(nx > x ? x + BW : x, y + BH / 2, nx > x ? nx : nx + BW, y + BH / 2) : arrow(x + BW / 2, y + BH, x + BW / 2, ny);
          return <path key={k} d={d} fill="none" strokeWidth="2" strokeLinecap="round" className={`${fade} ${k + 1 < lit ? "stroke-teal-600" : "stroke-gray-300"}`} />;
        })}
        {model.links.map((link, i) => {
          const [x, y] = where(i);
          const lines = wrapLabel(pick(link, lang), 19).slice(0, 5);
          const marked = model.highlight === `link${i + 1}`;
          return (
            <g key={i} data-part={`link${i + 1}`} data-highlighted={marked ? "true" : undefined} data-lit={i < lit ? "true" : "false"}>
              {marked ? <rect x={x - 4} y={y - 4} width={BW + 8} height={BH + 8} rx="10" fill="none" stroke={OUTLINE} strokeWidth="3" /> : null}
              <rect x={x} y={y} width={BW} height={BH} rx="8" strokeWidth="2" className={`${fade} ${i < lit ? "fill-teal-100 stroke-teal-600" : "fill-white stroke-gray-300"}`} />
              <text textAnchor="middle" fontSize="10" className="fill-gray-700">
                {lines.map((line, k) => (
                  <tspan key={k} x={x + BW / 2} y={y + BH / 2 + 3.5 - ((lines.length - 1) * LINE) / 2 + k * LINE}>
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
