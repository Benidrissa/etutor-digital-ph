/**
 * FR and EN messages stay in lockstep, and the labels story mode added exist
 * in both: a missing key shows the raw key (or, on the admin AI-cost
 * dashboard, the raw feature id `story_generation`) instead of a label.
 */

import { describe, expect, it } from "vitest";

import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

type Tree = { [key: string]: string | Tree };

function keys(tree: Tree, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [path] : keys(value, path);
  });
}

function at(tree: Tree, path: string): string | Tree | undefined {
  return path.split(".").reduce<string | Tree | undefined>(
    (node, key) => (node && typeof node === "object" ? node[key] : undefined),
    tree,
  );
}

describe("messages", () => {
  it("has the same keys in French and English", () => {
    const enKeys = new Set(keys(en as Tree));
    const frKeys = new Set(keys(fr as Tree));
    expect([...enKeys].filter((key) => !frKeys.has(key))).toEqual([]);
    expect([...frKeys].filter((key) => !enKeys.has(key))).toEqual([]);
  });

  it("labels story generation on the admin AI-cost dashboard", () => {
    expect(at(en as Tree, "Admin.analytics.feature.story_generation")).toBe("Story mode generation");
    expect(at(fr as Tree, "Admin.analytics.feature.story_generation")).toBe(
      "Génération du mode histoire",
    );
  });

  it.each([
    "Offline.downloadingStory",
    "Story.selfMarkPrompt",
    "Story.selfMarkGotIt",
    "Story.selfMarkNotYet",
    "Story.selfMarked",
    "Story.visualUnavailable",
  ])("has %s in both languages", (key) => {
    expect(typeof at(en as Tree, key)).toBe("string");
    expect(typeof at(fr as Tree, key)).toBe("string");
  });
});
