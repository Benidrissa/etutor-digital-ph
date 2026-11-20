/** The idea machines (#2740): parts, params, the picture per step, the alt text. */

import { describe, expect, it } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import table from "../../../backend/tests/fixtures/machine_parts_2740.json";
import {
  LINE_STEPS,
  NUMBER_LINE_MAX_TICKS,
  machineStartDelay,
  ballAt,
  formatNumber,
  groupsPlaced,
  machineAlt,
  numberLineLast,
  numberLineModel,
  partsOf,
  placeValueLast,
  placeValueModel,
} from "./machines";

describe("partsOf", () => {
  it("gives the lists of the backend's machine_parts on the shared table", () => {
    expect(table.length).toBeGreaterThanOrEqual(19);
    for (const row of table) expect(partsOf(row.visual, row.params), JSON.stringify(row)).toEqual(row.parts);
  });

  it("treats a null mark like an absent one", () => {
    expect(partsOf("number_line", { from: 0, to: 9, mark: null })).toEqual(["from", "to"]);
  });
});

describe("params", () => {
  it("place_value takes 0 to 12 digits and a part present in n", () => {
    expect(placeValueModel({ n: 4305892176, reveal: "groups", highlight: "millions" })).not.toBeNull();
    expect(placeValueModel({ n: 4.0 })).not.toBeNull();
    for (const bad of [
      { n: -1 },
      { n: 10 ** 12 },
      { n: 2.5 },
      { n: "12" },
      {},
      { n: 5, reveal: "slow" },
      { n: 5, highlight: "millions" },
    ]) {
      expect(placeValueModel(bad), JSON.stringify(bad)).toBeNull();
    }
    expect(placeValueModel(null)).toBeNull();
  });

  it("number_line needs from < to, a mark inside, at most 20 ticks and a present highlight", () => {
    expect(numberLineModel({ from: 0, to: 100, mark: 37, step: 5, highlight: "mark" })).not.toBeNull();
    expect(numberLineModel({ from: 0, to: 100, mark: null })).not.toBeNull();
    for (const bad of [
      { from: 1, to: 1 },
      { from: 0 },
      { from: 0, to: 10, mark: 11 },
      { from: 0, to: 10, step: 0 },
      { from: 0, to: 105, step: 5 },
      { from: 0, to: 10, highlight: "mark" },
      { from: 0, to: Infinity },
    ]) {
      expect(numberLineModel(bad), JSON.stringify(bad)).toBeNull();
    }
  });

  it("chooses its own ticks, ends included, and keeps the given step", () => {
    expect(numberLineModel({ from: 0, to: 100, step: 25 })?.ticks).toEqual([0, 25, 50, 75, 100]);
    expect(numberLineModel({ from: 0, to: 10 })?.ticks).toEqual([0, 2, 4, 6, 8, 10]);
    expect(numberLineModel({ from: -5, to: 5, step: 5 })?.ticks).toEqual([-5, 0, 5]);
    expect(numberLineModel({ from: 3, to: 98, step: 10 })?.ticks).toEqual([3, 13, 23, 33, 43, 53, 63, 73, 83, 93, 98]);
  });
});

describe("the picture as a function of the step", () => {
  const groups = placeValueModel({ n: 4305892176 })!;
  const all = placeValueModel({ n: 4305892176, reveal: "all" })!;

  it("drops the groups of digits from the right, one per step", () => {
    expect(placeValueLast(groups)).toBe(4);
    expect([0, 1, 2, 3, 4, 9, -1].map((step) => groupsPlaced(groups, step))).toEqual([0, 1, 2, 3, 4, 4, 0]);
  });

  it("drops everything at once when reveal is all", () => {
    expect(placeValueLast(all)).toBe(1);
    expect([0, 1, 5].map((step) => groupsPlaced(all, step))).toEqual([0, 4, 4]);
  });

  it("rolls the ball from from to mark, and keeps it still without a mark", () => {
    const line = numberLineModel({ from: 0, to: 100, mark: 40 })!;
    expect(numberLineLast(line)).toBe(LINE_STEPS);
    expect([0, 1, 2, 4, 9].map((step) => ballAt(line, step))).toEqual([0, 10, 20, 40, 40]);
    const bare = numberLineModel({ from: 2, to: 9 })!;
    expect(numberLineLast(bare)).toBe(0);
    expect(ballAt(bare, 3)).toBe(2);
  });
});

function sayIn(lang: "fr" | "en") {
  const messages = (lang === "fr" ? frMessages : enMessages).Story as unknown as Record<string, string>;
  // The messages used here are plain or one plural: enough of ICU for a test.
  return (key: string, values: Record<string, string | number> = {}) => {
    let text = messages[key];
    const plural = /^\{count, plural, one \{([^}]*)\} other \{([^}]*)\}\}$/.exec(text);
    if (plural) text = Number(values.count) === 1 ? plural[1] : plural[2];
    return text.replace(/#/g, String(values.count)).replace(/\{(\w+)\}/g, (_, name) => String(values[name]));
  };
}

describe("alt text", () => {
  const alt = (n: number, lang: "fr" | "en") => machineAlt("place_value", { n }, lang, sayIn(lang));

  it("reads the issue's examples", () => {
    expect(alt(4305892176, "en")).toBe("4,305,892,176: 4 billion, 305 million, 892 thousand, 176");
    expect(alt(4305892176, "fr")).toBe("4 305 892 176 : 4 milliards, 305 millions, 892 mille, 176");
  });

  it("uses French plurals and skips the zero groups", () => {
    expect(alt(1000000, "fr")).toBe("1 000 000 : 1 million");
    expect(alt(2000000000, "fr")).toBe("2 000 000 000 : 2 milliards");
    expect(alt(1001000, "fr")).toBe("1 001 000 : 1 million, mille");
    expect(alt(1000, "fr")).toBe("1 000 : mille");
    expect(alt(1000000007, "en")).toBe("1,000,000,007: 1 billion, 7");
  });

  it("gives just the number for a small one", () => {
    expect(alt(0, "en")).toBe("0");
    expect(alt(176, "fr")).toBe("176");
  });

  it("describes a number line, its ends and where the ball stops", () => {
    expect(machineAlt("number_line", { from: -5, to: 5, mark: 0.5 }, "en", sayIn("en"))).toBe(
      "Number line from -5 to 5. The ball stops at 0.5.",
    );
    expect(machineAlt("number_line", { from: 0, to: 1500, mark: 1000 }, "fr", sayIn("fr"))).toBe(
      "Droite numérique de 0 à 1 500. La balle s'arrête à 1 000.",
    );
    expect(machineAlt("number_line", { from: 0, to: 10 }, "en", sayIn("en"))).toBe("Number line from 0 to 10.");
  });

  it("has no text for params that cannot be drawn", () => {
    expect(machineAlt("place_value", { n: -3 }, "en", sayIn("en"))).toBeNull();
    expect(machineAlt("number_line", { from: 3, to: 1 }, "en", sayIn("en"))).toBeNull();
  });

  it("formats numbers per language", () => {
    expect(formatNumber(1234.5, "fr")).toBe("1 234,5");
    expect(formatNumber(1234.5, "en")).toBe("1,234.5");
  });
});

describe("hostile number lines (#2740 review)", () => {
  it("ends for huge values and keeps ticks strictly increasing", () => {
    for (const params of [
      { from: 1e16, to: 1e16 + 4, step: 1 },
      { from: 1e16, to: 1e16 + 4 },
      { from: 1e21, to: 1e21 + 1000 },
      { from: 0, to: 1e-300 },
    ]) {
      const model = numberLineModel(params);
      const ticks = model?.ticks ?? [];
      expect(ticks.length).toBeLessThanOrEqual(NUMBER_LINE_MAX_TICKS + 4);
      ticks.slice(1).forEach((t, i) => expect(t).toBeGreaterThan(ticks[i]));
    }
  });
  it("starts the ticks at from when a step is given", () => {
    expect(numberLineModel({ from: 3, to: 13, step: 5 })?.ticks).toEqual([3, 8, 13]);
  });
  it("decides when a machine starts", () => {
    const base = { hasMachine: true, introOpen: false, beatOn: false, revisit: false, cut: false };
    expect(machineStartDelay({ ...base, machineAt: 400 })).toBe(400);
    expect(machineStartDelay(base)).toBe(0);
    expect(machineStartDelay({ ...base, cut: true, machineAt: 400 })).toBe(0);
    expect(machineStartDelay({ ...base, beatOn: true })).toBeNull();
    expect(machineStartDelay({ ...base, revisit: true })).toBeNull();
    expect(machineStartDelay({ ...base, hasMachine: false })).toBeNull();
  });
});
