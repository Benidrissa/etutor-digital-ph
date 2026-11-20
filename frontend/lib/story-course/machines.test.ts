/** The idea machines (#2740): parts, params, the picture per step, the alt text. */

import { describe, expect, it } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import table from "../../../backend/tests/fixtures/machine_parts_2740.json";
import {
  LINE_STEPS,
  balanceLast,
  balanceModel,
  beamAngle,
  chainLast,
  chainModel,
  cycleLast,
  cycleModel,
  isMachineVisual,
  linksLit,
  markerAt,
  wrapLabel,
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
    expect(table.length).toBeGreaterThanOrEqual(42);
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

const label = (en: string, fr = en) => ({ en, fr });
const labels = (n: number) => Array.from({ length: n }, (_, i) => label(`L${i + 1}`));
const SIDES = { left: { label: label("Costs", "Coûts"), value: 1200 }, right: { label: label("Income", "Recettes"), value: 950 } };

describe("balance (#2756)", () => {
  it("tilts toward the larger value and stays level when equal", () => {
    const heavy = balanceModel(SIDES)!;
    expect(heavy.heavier).toBe("left");
    expect(balanceLast(heavy)).toBe(1);
    expect(beamAngle(heavy, 0)).toBe(0);
    expect(beamAngle(heavy, 1)).toBeLessThan(0);
    const right = balanceModel({ ...SIDES, left: { ...SIDES.left, value: 5 } })!;
    expect(right.heavier).toBe("right");
    expect(beamAngle(right, 1)).toBeGreaterThan(0);
    const equal = balanceModel({ ...SIDES, right: { ...SIDES.right, value: 1200 } })!;
    expect(equal.heavier).toBeNull();
    expect(balanceLast(equal)).toBe(0);
    expect(beamAngle(equal, 1)).toBe(0);
  });

  it("tilts more for a bigger gap, within bounds, and clamps the step", () => {
    const at = (l: number, r: number) => Math.abs(beamAngle(balanceModel({ left: { ...SIDES.left, value: l }, right: { ...SIDES.right, value: r } })!, 1));
    expect(at(100, 99)).toBe(6);
    expect(at(100000, 0)).toBe(16);
    expect(at(100, 50)).toBeGreaterThan(at(100, 90));
    expect(beamAngle(balanceModel(SIDES)!, 99)).toBe(beamAngle(balanceModel(SIDES)!, 1));
  });

  it("refuses values and labels outside the rules, and a highlight that is not a part", () => {
    for (const bad of [
      { ...SIDES, left: { ...SIDES.left, value: -1 } },
      { ...SIDES, left: { ...SIDES.left, value: 100001 } },
      { ...SIDES, left: { ...SIDES.left, value: true } },
      { ...SIDES, left: { ...SIDES.left, value: NaN } },
      { ...SIDES, right: { label: label("x".repeat(41)), value: 1 } },
      { ...SIDES, right: { label: { en: "only" }, value: 1 } },
      { left: SIDES.left },
      { ...SIDES, highlight: "mark" },
      { ...SIDES, highlight: 3 },
    ]) expect(balanceModel(bad), JSON.stringify(bad)).toBeNull();
    expect(balanceModel({ ...SIDES, highlight: "beam" })?.highlight).toBe("beam");
    expect(balanceModel(null)).toBeNull();
  });
});

describe("cycle (#2756)", () => {
  it("visits every stage once from start and ends where it began", () => {
    for (const [count, start] of [[3, 1], [4, 3], [6, 6]] as const) {
      const model = cycleModel({ stages: labels(count), start })!;
      expect(cycleLast(model)).toBe(count);
      const path = Array.from({ length: count + 1 }, (_, step) => markerAt(model, step));
      expect(path[0]).toBe(start - 1);
      expect(path[count]).toBe(start - 1);
      expect([...path.slice(0, count)].sort()).toEqual(Array.from({ length: count }, (_, i) => i));
      expect(markerAt(model, 99)).toBe(start - 1);
    }
  });

  it("starts at stage 1 by default and checks start, count and labels", () => {
    expect(cycleModel({ stages: labels(3) })?.start).toBe(0);
    expect(cycleModel({ stages: labels(4), start: 2.0 })?.start).toBe(1);
    for (const bad of [
      { stages: labels(2) },
      { stages: labels(7) },
      { stages: "rain" },
      { stages: [...labels(2), label("")] },
      { stages: labels(3), start: 0 },
      { stages: labels(3), start: 4 },
      { stages: labels(3), start: 1.5 },
      { stages: labels(3), start: true },
      { stages: labels(3), highlight: "stage4" },
      {},
    ]) expect(cycleModel(bad), JSON.stringify(bad)).toBeNull();
    expect(cycleModel({ stages: labels(3), highlight: "stage3" })?.highlight).toBe("stage3");
  });
});

describe("cause_chain (#2756)", () => {
  it("lights the links in order, one more at each step", () => {
    const model = chainModel({ links: labels(4) })!;
    expect(chainLast(model)).toBe(4);
    expect([0, 1, 2, 3, 4, 9].map((step) => linksLit(model, step))).toEqual([0, 1, 2, 3, 4, 4]);
  });

  it("takes 2 to 5 labels", () => {
    expect(chainModel({ links: labels(2) })).not.toBeNull();
    expect(chainModel({ links: labels(5), highlight: "link5" })?.highlight).toBe("link5");
    for (const bad of [{ links: labels(1) }, { links: labels(6) }, { links: labels(3), highlight: "link4" }, { links: [label("a"), { en: "b" }] }, {}]) {
      expect(chainModel(bad), JSON.stringify(bad)).toBeNull();
    }
  });
});

describe("the new machines (#2756)", () => {
  it("are idea machines", () => {
    for (const name of ["balance", "cycle", "cause_chain"]) expect(isMachineVisual(name)).toBe(true);
    expect(isMachineVisual("venn_primes")).toBe(false);
  });

  it("keep their parts whatever start and highlight say", () => {
    expect(partsOf("cycle", { stages: labels(3), start: 9, highlight: "x" })).toEqual(["stage1", "stage2", "stage3"]);
    expect(partsOf("balance", { ...SIDES, highlight: 4 })).toEqual(["left", "right", "beam"]);
  });

  it("wraps a label inside a line width, cutting a word that is too long", () => {
    expect(wrapLabel("Higher prices for all", 14)).toEqual(["Higher prices", "for all"]);
    expect(wrapLabel("x".repeat(40), 14).map((line) => line.length)).toEqual([14, 14, 12]);
    expect(wrapLabel("  ", 14)).toEqual([]);
    for (const line of wrapLabel("a bb ccc dddd eeeee ffffff ggggggg hhhhhhhh", 13)) expect(line.length).toBeLessThanOrEqual(13);
  });

  describe("alt text", () => {
    const say = (lang: "fr" | "en") => sayIn(lang);
    const chain = { links: [label("Less rain", "Moins de pluie"), label("Dry well", "Puits à sec"), label("Poor harvest", "Mauvaise récolte")] };
    const cycle = { stages: [label("Evaporation", "Évaporation"), label("Rain", "Pluie"), label("Run-off", "Ruissellement")], start: 2 };

    it("reads a balance with its heavier side, or balanced", () => {
      expect(machineAlt("balance", SIDES, "en", say("en"))).toBe("Scale comparing Costs (1,200) with Income (950). The heavier side is Costs.");
      expect(machineAlt("balance", SIDES, "fr", say("fr"))).toBe("Balance comparant Coûts (1 200) et Recettes (950). Le côté le plus lourd : Coûts.");
      expect(machineAlt("balance", { ...SIDES, left: { ...SIDES.left, value: 10 } }, "en", say("en"))).toContain("The heavier side is Income");
      expect(machineAlt("balance", { ...SIDES, right: { ...SIDES.right, value: 1200 } }, "en", say("en"))).toContain("balanced");
      expect(machineAlt("balance", { ...SIDES, right: { ...SIDES.right, value: 1200 } }, "fr", say("fr"))).toContain("à l'équilibre");
    });

    it("reads a cycle as its stages, back to the first", () => {
      expect(machineAlt("cycle", cycle, "en", say("en"))).toBe("Cycle of 3 stages: Evaporation, Rain, Run-off, then back to Rain.");
      expect(machineAlt("cycle", cycle, "fr", say("fr"))).toBe("Cycle de 3 étapes : Évaporation, Pluie, Ruissellement, puis retour à Pluie.");
    });

    it("reads a chain as its links, each leading to the next", () => {
      expect(machineAlt("cause_chain", chain, "en", say("en"))).toBe("Chain of 3 causes, each leading to the next: Less rain, Dry well, Poor harvest.");
      expect(machineAlt("cause_chain", chain, "fr", say("fr"))).toBe("Chaîne de 3 causes, chacune menant à la suivante : Moins de pluie, Puits à sec, Mauvaise récolte.");
    });

    it("has no text for params that cannot be drawn", () => {
      for (const visual of ["balance", "cycle", "cause_chain"]) expect(machineAlt(visual, {}, "en", say("en"))).toBeNull();
    });
  });
});
