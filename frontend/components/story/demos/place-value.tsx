"use client";

import { useTranslations } from "next-intl";

import { groupsPlaced, placeValueLast, placeValueModel } from "@/lib/story-course/machines";

import { OUTLINE, useMachineStep, type MachineProps } from "./machine";

const CELL = 22;
const GAP = 10;

/**
 * Digits drop into their place-value columns (#2740), three at a time from the
 * right, or all at once. What shows at each step comes from `groupsPlaced`.
 */
export default function PlaceValue({ params, play, reveal, reduced }: MachineProps) {
  const t = useTranslations("Story");
  const model = placeValueModel(params);
  const last = model ? placeValueLast(model) : 0;
  const { step, next } = useMachineStep(last, { play, reveal, reduced });
  if (!model) return null;
  const placed = groupsPlaced(model, step);
  // Highest group on the left; the top one may hold fewer than three digits.
  const shown = [...model.groups].reverse().map((group) => {
    const at = model.groups.indexOf(group);
    const digits = model.digits.slice(Math.max(0, model.digits.length - 3 * (at + 1)), model.digits.length - 3 * at);
    return { group, at, digits, width: digits.length * CELL };
  });
  const columns = shown.map((c, i) => ({
    ...c,
    x: 4 + shown.slice(0, i).reduce((sum, p) => sum + p.width, 0) + i * GAP,
  }));
  const width = columns[columns.length - 1].x + columns[columns.length - 1].width + 4;
  return (
    <div>
      <svg viewBox={`0 0 ${width} 76`} className="mx-auto block w-full" style={{ maxWidth: width * 2 }} aria-hidden="true">
        {columns.map((c) => {
          const dropped = c.at < placed;
          const marked = model.highlight === c.group;
          return (
            <g key={c.group} data-part={c.group} data-highlighted={marked ? "true" : undefined}>
              <text x={c.x + c.width / 2} y="11" textAnchor="middle" fontSize="9" className="fill-gray-600">
                {t(`machineLabel_${c.group}`)}
              </text>
              <rect x={c.x} y="16" width={c.width} height="46" rx="4" className="fill-white stroke-gray-300" />
              {marked ? (
                <rect x={c.x - 3} y="13" width={c.width + 6} height="52" rx="6" fill="none" stroke={OUTLINE} strokeWidth="3" />
              ) : null}
              <g
                data-dropped={dropped ? "true" : "false"}
                style={{
                  transform: dropped ? "translateY(0)" : "translateY(-22px)",
                  opacity: dropped ? 1 : 0,
                  transition: reduced ? "none" : "transform 0.5s ease-in, opacity 0.3s",
                }}
              >
                {[...c.digits].map((d, i) => (
                  <text key={i} x={c.x + CELL * i + CELL / 2} y="48" textAnchor="middle" fontSize="26" className="fill-teal-700 font-semibold">
                    {d}
                  </text>
                ))}
              </g>
            </g>
          );
        })}
      </svg>
      {reduced && step < last && !reveal ? <NextButton label={t("machineNext")} onClick={next} /> : null}
    </div>
  );
}

function NextButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mx-auto mt-2 block min-h-11 min-w-11 rounded-lg bg-teal-600 px-5 font-semibold text-white hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
    >
      {label}
    </button>
  );
}
