/**
 * FR and EN messages stay in lockstep, and the labels story mode added exist
 * in both: a missing key shows the raw key (or, on the admin AI-cost
 * dashboard, the raw feature id `story_generation`) instead of a label.
 *
 * The module story's ICU selects must name the same branches in both
 * languages, or one language would fall back to `other` for a quiz.
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

  // The per-lesson story mode is gone: its tab, panel and per-unit download
  // label have no caller left, so their labels must not linger.
  it.each(["LessonStory", "LessonMediaTabs.storyTab", "Offline.downloadingStory"])(
    "no longer has the per-lesson %s in either language",
    (key) => {
      expect(at(en as Tree, key)).toBeUndefined();
      expect(at(fr as Tree, key)).toBeUndefined();
    },
  );

  it.each([
    "Offline.downloadingModuleStory",
    "ModuleOverview.storyCard.title",
    "ModuleOverview.storyCard.start",
    "ModuleOverview.storyCard.resume",
    "ModuleOverview.storyCard.done",
    "ModuleOverview.storyCard.generating",
    "ModuleOverview.storyCard.subscribersOnly",
    "ModuleOverview.storyCard.unavailable",
    "ModuleStory.pageTitle",
    "ModuleStory.regionLabel",
    "ModuleStory.eyebrow",
    "ModuleStory.backToModule",
    "ModuleStory.loading",
    "ModuleStory.generating",
    "ModuleStory.generatingDescription",
    "ModuleStory.leaveHint",
    "ModuleStory.timeout",
    "ModuleStory.unavailable",
    "ModuleStory.unavailableHint",
    "ModuleStory.disabled",
    "ModuleStory.offline",
    "ModuleStory.failed",
    "ModuleStory.retry",
    "ModuleStory.chapters",
    "ModuleStory.chapterOf",
    "ModuleStory.chapterDone",
    "ModuleStory.chapterCurrent",
    "ModuleStory.chapterUpcoming",
    "ModuleStory.kind",
    "ModuleStory.chapterComplete",
    "ModuleStory.score",
    "ModuleStory.points",
    "ModuleStory.lessonRecorded",
    "ModuleStory.nextChapter",
    "ModuleStory.seeSummary",
    "ModuleStory.moduleComplete",
    "ModuleStory.stillToDo",
    "ModuleStory.stillToDoHint",
    "ModuleStory.allDone",
    "ModuleStory.openUnit",
    "Story.selfMarkPrompt",
    "Story.selfMarkGotIt",
    "Story.selfMarkNotYet",
    "Story.selfMarked",
    "Story.visualUnavailable",
    "Navigation.story",
  ])("has %s in both languages", (key) => {
    expect(typeof at(en as Tree, key)).toBe("string");
    expect(typeof at(fr as Tree, key)).toBe("string");
  });

  it.each(["ModuleStory.kind", "ModuleStory.openUnit"])(
    "%s has the quiz, case and other branches in both languages",
    (key) => {
      for (const tree of [en, fr]) {
        const message = at(tree as Tree, key);
        expect(typeof message).toBe("string");
        for (const branch of ["quiz {", "case {", "other {"]) {
          expect(message).toContain(branch);
        }
      }
    },
  );
});
