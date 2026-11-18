/**
 * Tests for story-course answer acceptance (format Appendix A.5).
 *
 * The acceptance table in A.5 is a promise to the child: the forms listed
 * there must not cost her a mark. Each row is pinned here.
 */

import { describe, expect, it } from "vitest";

import {
  findTrap,
  isIndexForm,
  matchAnswer,
  normalizeIndexForm,
  normalizeTime,
  parseLooseNumber,
  scoreAttempt,
  starsFor,
  text,
} from "./answer";
import type { Question } from "./types";

const TIMES = "×";
const MINUS = "−";

describe("parseLooseNumber", () => {
  it("reads plain numbers", () => {
    expect(parseLooseNumber("12")?.value).toBe(12);
    expect(parseLooseNumber(" 12 ")?.value).toBe(12);
  });

  it("accepts space thousands (A.2)", () => {
    expect(parseLooseNumber("4 284")?.value).toBe(4284);
  });

  it("accepts thousands commas", () => {
    expect(parseLooseNumber("4,284")?.value).toBe(4284);
    expect(parseLooseNumber("4,284")?.decimalCommaUsed).toBe(false);
  });

  it("accepts a decimal comma but flags it for the reminder", () => {
    const got = parseLooseNumber("3,25");
    expect(got?.value).toBe(3.25);
    expect(got?.decimalCommaUsed).toBe(true);
  });

  it("accepts the U+2212 minus sign", () => {
    expect(parseLooseNumber(`${MINUS}12`)?.value).toBe(-12);
  });

  it("ignores a trailing unit", () => {
    expect(parseLooseNumber("12 cm")?.value).toBe(12);
  });

  it("refuses leading junk and empty input", () => {
    expect(parseLooseNumber("cm 12")).toBeNull();
    expect(parseLooseNumber("")).toBeNull();
    expect(parseLooseNumber("abc")).toBeNull();
  });
});

describe("number questions", () => {
  it("accepts every A.5 form", () => {
    for (const typed of ["12", " 12", "12 mangoes", "012"]) {
      expect(matchAnswer(typed, 12, "number").correct).toBe(true);
    }
  });

  it("accepts a decimal comma with the reminder flag", () => {
    const got = matchAnswer("3,25", 3.25, "number");
    expect(got.correct).toBe(true);
    expect(got.decimalCommaUsed).toBe(true);
  });

  it("rejects a different value", () => {
    expect(matchAnswer("13", 12, "number").correct).toBe(false);
  });

  it("treats 2.10 and 2.1 as the same number", () => {
    expect(matchAnswer("2.10", 2.1, "number").correct).toBe(true);
  });
});

describe("exact_text questions", () => {
  it("compares the same characters once spaces are removed", () => {
    expect(matchAnswer("0.047", "0.047", "exact_text").correct).toBe(true);
    expect(matchAnswer(" 0.047 ", "0.047", "exact_text").correct).toBe(true);
  });

  it("keeps 2.1 different from 2.10", () => {
    expect(matchAnswer("2.10", "2.1", "exact_text").correct).toBe(false);
    expect(matchAnswer("2.1", "2.10", "exact_text").correct).toBe(false);
  });
});

describe("index_form questions", () => {
  const answer = `2³ ${TIMES} 3² ${TIMES} 5`;

  it("accepts superscripts, carets and x", () => {
    expect(matchAnswer(answer, answer, "index_form").correct).toBe(true);
    expect(matchAnswer("2^3 x 3^2 x 5", answer, "index_form").correct).toBe(true);
    expect(matchAnswer("2^3*3^2*5", answer, "index_form").correct).toBe(true);
  });

  it("accepts a reordered product", () => {
    expect(
      matchAnswer(`3² ${TIMES} 2³ ${TIMES} 5`, answer, "index_form").correct,
    ).toBe(true);
  });

  it("does not accept the expanded form", () => {
    const expanded = `2 ${TIMES} 2 ${TIMES} 2 ${TIMES} 3 ${TIMES} 3 ${TIMES} 5`;
    expect(matchAnswer(expanded, answer, "index_form").correct).toBe(false);
  });

  it("flags the expanded form so the index-form hint can be shown", () => {
    const expanded = `2 ${TIMES} 2 ${TIMES} 2 ${TIMES} 3 ${TIMES} 3 ${TIMES} 5`;
    const got = matchAnswer(expanded, answer, "index_form", { requireIndex: true });
    expect(got.correct).toBe(false);
    expect(got.needsIndexForm).toBe(true);
  });

  it("does not flag a genuinely wrong factorisation", () => {
    const got = matchAnswer(`2³ ${TIMES} 3 ${TIMES} 5`, answer, "index_form", {
      requireIndex: true,
    });
    expect(got.correct).toBe(false);
    expect(got.needsIndexForm).toBeUndefined();
  });

  it("normalizes consistently", () => {
    expect(normalizeIndexForm("2^3 x 3^2 x 5")).toBe(normalizeIndexForm(answer));
  });

  it("isIndexForm distinguishes powers from repeats", () => {
    expect(isIndexForm(answer)).toBe(true);
    expect(isIndexForm(`2 ${TIMES} 2 ${TIMES} 2`)).toBe(false);
  });
});

describe("time questions", () => {
  it("accepts 8:36, 08h36 and 8.36", () => {
    for (const typed of ["08:36", "8:36", "08h36", "8h36", "8.36"]) {
      expect(matchAnswer(typed, "08:36", "time").correct).toBe(true);
    }
  });

  it("accepts a 12-hour time with am/pm", () => {
    expect(matchAnswer("8.36 am", "08:36", "time").correct).toBe(true);
    expect(matchAnswer("8.36 pm", "20:36", "time").correct).toBe(true);
  });

  it("rejects nonsense", () => {
    expect(normalizeTime("99:99")).toBeNull();
    expect(matchAnswer("tomorrow", "08:36", "time").correct).toBe(false);
  });
});

describe("list questions", () => {
  it("accepts comma-separated items", () => {
    expect(matchAnswer("31, 37", [31, 37], "list").correct).toBe(true);
    expect(matchAnswer("31,37", [31, 37], "list").correct).toBe(true);
  });

  it("respects ascending order", () => {
    expect(
      matchAnswer("37, 31", [31, 37], "list", { order: "ascending" }).correct,
    ).toBe(false);
    expect(matchAnswer("37, 31", [31, 37], "list", { order: "any" }).correct).toBe(true);
  });

  it("rejects an extra or missing item", () => {
    expect(matchAnswer("31, 33, 37", [31, 37], "list").correct).toBe(false);
    expect(matchAnswer("31", [31, 37], "list").correct).toBe(false);
  });
});

describe("choice questions", () => {
  it("compares the option id", () => {
    expect(matchAnswer("c", "c", "choice").correct).toBe(true);
    expect(matchAnswer("C", "c", "choice").correct).toBe(true);
    expect(matchAnswer("b", "c", "choice").correct).toBe(false);
  });
});

describe("findTrap", () => {
  const question = {
    type: "index_form" as const,
    require_index: true,
    traps: [
      {
        answer: `2 ${TIMES} 2 ${TIMES} 2 ${TIMES} 3 ${TIMES} 3 ${TIMES} 5`,
        misconception: "m_not_index_form",
        hint: { en: "Use powers.", fr: "Utilise les puissances." },
      },
      {
        answer: `2³ ${TIMES} 3 ${TIMES} 5`,
        misconception: "m_lost_factor",
        hint: { en: "Multiply back.", fr: "Remultiplie." },
      },
    ],
  };

  it("matches a trap with the same generosity as the answer", () => {
    expect(findTrap("2*2*2*3*3*5", question)?.misconception).toBe("m_not_index_form");
    expect(findTrap("2^3 x 3 x 5", question)?.misconception).toBe("m_lost_factor");
  });

  it("returns null when no trap matches", () => {
    expect(findTrap("7", question)).toBeNull();
  });
});

describe("scoreAttempt — the A.5 flow", () => {
  const question: Question = {
    id: "q5",
    type: "number",
    prompt: { en: "Find the HCF of 24 and 36.", fr: "Trouve le PGCD de 24 et 36." },
    answer: 12,
    traps: [
      {
        answer: 72,
        misconception: "m_hcf_lcm_swap",
        hint: { en: "That is the LCM.", fr: "C'est le PPCM." },
      },
    ],
    hints: [{ en: "Use the Venn overlap.", fr: "Utilise l'intersection." }],
    explanation: { en: "24 = 2³ × 3.", fr: "24 = 2³ × 3." },
  };

  it("gives 2 points on the first try", () => {
    const got = scoreAttempt("12", question, 0);
    expect(got.result.correct).toBe(true);
    expect(got.points).toBe(2);
    expect(got.revealExplanation).toBe(true);
  });

  it("gives 1 point on the second try", () => {
    const got = scoreAttempt("12", question, 1);
    expect(got.result.correct).toBe(true);
    expect(got.points).toBe(1);
  });

  it("gives the trap's own hint on a first wrong try, not the generic one", () => {
    const got = scoreAttempt("72", question, 0);
    expect(got.result.correct).toBe(false);
    expect(got.points).toBe(0);
    expect(got.trap?.misconception).toBe("m_hcf_lcm_swap");
    expect(got.hint?.en).toBe("That is the LCM.");
    expect(got.revealExplanation).toBe(false);
  });

  it("falls back to the first generic hint when no trap matches", () => {
    const got = scoreAttempt("5", question, 0);
    expect(got.hint?.en).toBe("Use the Venn overlap.");
  });

  it("reveals the explanation after the second wrong try", () => {
    const got = scoreAttempt("5", question, 1);
    expect(got.revealExplanation).toBe(true);
    expect(got.hint).toBeNull();
  });

  it("honours a points override", () => {
    const got = scoreAttempt("12", { ...question, points: 5 }, 0);
    expect(got.points).toBe(5);
  });

  it("honours custom reward values", () => {
    const got = scoreAttempt("12", question, 1, { first_try: 3, second_try: 2 });
    expect(got.points).toBe(2);
  });
});

describe("text", () => {
  it("picks the language, then falls back", () => {
    expect(text({ en: "Hello", fr: "Bonjour" }, "fr")).toBe("Bonjour");
    expect(text({ en: "Hello" }, "fr", "en")).toBe("Hello");
    expect(text(undefined, "fr")).toBe("");
  });
});

describe("starsFor", () => {
  it("applies the A.11 thresholds", () => {
    expect(starsFor(1)).toBe(3);
    expect(starsFor(0.85)).toBe(3);
    expect(starsFor(0.7)).toBe(2);
    expect(starsFor(0.3)).toBe(1);
    expect(starsFor(0)).toBe(0);
  });
});
