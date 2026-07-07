import { describe, it, expect } from "vitest";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";

import { normalizeMarkdown } from "./markdown-utils";

interface MdNode {
  type: string;
  children?: MdNode[];
}

/** Count nodes of a given type in a parsed mdast tree. */
function countType(md: string, type: string): number {
  const tree = unified().use(remarkParse).use(remarkGfm).parse(md) as MdNode;
  let n = 0;
  const walk = (node: MdNode) => {
    if (node.type === type) n++;
    for (const child of node.children ?? []) walk(child);
  };
  walk(tree);
  return n;
}

describe("normalizeMarkdown", () => {
  it("makes a table parse when it directly follows a text line", () => {
    const md = [
      "2) L'architecture d'un document standardisé :",
      "| Partie | Rôle | Source |",
      "|---|---|---|",
      "| En-tête | Métadonnées | p.248 |",
    ].join("\n");

    // Before normalization remark-gfm does not recognize the table.
    expect(countType(md, "table")).toBe(0);
    // After normalization it does.
    expect(countType(normalizeMarkdown(md), "table")).toBe(1);
  });

  it("handles multiple tables in one string", () => {
    const md = [
      "Intro paragraph.",
      "| A | B |",
      "|---|---|",
      "| 1 | 2 |",
      "Another line right before a second table:",
      "| C | D |",
      "|---|---|",
      "| 3 | 4 |",
    ].join("\n");

    expect(countType(normalizeMarkdown(md), "table")).toBe(2);
  });

  it("leaves an already-spaced table untouched (idempotent)", () => {
    const md = ["Intro.", "", "| A | B |", "|---|---|", "| 1 | 2 |"].join("\n");
    expect(normalizeMarkdown(md)).toBe(md);
    // Running twice is stable.
    expect(normalizeMarkdown(normalizeMarkdown(md))).toBe(normalizeMarkdown(md));
  });

  it("does not disturb pipe lines inside fenced code blocks", () => {
    const md = ["```", "text before", "| not | a | table |", "```"].join("\n");
    expect(normalizeMarkdown(md)).toBe(md);
    expect(countType(normalizeMarkdown(md), "table")).toBe(0);
  });

  it("returns non-string / empty input unchanged", () => {
    expect(normalizeMarkdown("")).toBe("");
    // @ts-expect-error exercising the runtime guard
    expect(normalizeMarkdown(null)).toBe(null);
  });
});
