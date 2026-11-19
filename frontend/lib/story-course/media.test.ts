import { afterEach, describe, expect, it } from "vitest";

import { figureLanguage, figureUrl, savesData, storyFigureUrls } from "./media";
import type { StoryCourse } from "./types";

const FIGURE = "65bb9ff9-1111-4111-8111-111111111111";
const ILLUSTRATION = "22222222-2222-4222-8222-222222222222";

function story(extra: Partial<StoryCourse> = {}): StoryCourse {
  return {
    languages: { target: "fr", home: "en" },
    props: [
      {
        id: "poster",
        kind: "figure",
        label: { en: "the poster", fr: "l'affiche" },
        query: "poster",
        figure: { source_image_id: FIGURE },
      },
      {
        id: "sketch",
        kind: "figure",
        label: { en: "the sketch", fr: "le croquis" },
        query: "sketch",
        figure: { generated_image_id: ILLUSTRATION },
      },
      { id: "basket", kind: "sticker", label: { en: "a basket", fr: "un panier" }, query: "basket" },
    ],
    chapters: [
      {
        id: "ch1",
        scenes: [
          {
            id: "s1",
            steps: [
              { type: "show", visual: "image", params: { source_image_id: FIGURE } },
              { type: "show", visual: "prop", params: { prop: "poster" } },
              { type: "show", visual: "image", params: { generated_image_id: "../etc/passwd" } },
            ],
          },
        ],
      },
    ],
    ...extra,
  } as unknown as StoryCourse;
}

describe("storyFigureUrls (#2709)", () => {
  it("lists each figure and illustration the story shows, once, in the lesson's language", () => {
    expect(storyFigureUrls(story())).toEqual([
      `/api/v1/source-images/${FIGURE}/data?lang=fr`,
      `/api/v1/images/${ILLUSTRATION}/data`,
    ]);
  });

  it("falls back to the home language, then English, when the target has no figures", () => {
    expect(figureLanguage("fr", "en")).toBe("fr");
    expect(figureLanguage("bm", "fr")).toBe("fr");
    expect(figureLanguage("bm", "wo")).toBe("en");
  });

  it("never builds a url from an id that is not one", () => {
    expect(figureUrl({ source_image_id: "x/../y" }, "fr")).toBeUndefined();
    expect(figureUrl({ generated_image_id: ILLUSTRATION }, "en")).toBe(`/api/v1/images/${ILLUSTRATION}/data`);
    expect(figureUrl(undefined, "en")).toBeUndefined();
  });
});

describe("savesData", () => {
  const original = Object.getOwnPropertyDescriptor(navigator, "connection");
  afterEach(() => {
    if (original) Object.defineProperty(navigator, "connection", original);
    else Reflect.deleteProperty(navigator, "connection");
  });

  it("is true on data saver or a 2G link", () => {
    Object.defineProperty(navigator, "connection", { value: { saveData: true }, configurable: true });
    expect(savesData()).toBe(true);
    Object.defineProperty(navigator, "connection", { value: { effectiveType: "2g" }, configurable: true });
    expect(savesData()).toBe(true);
    Object.defineProperty(navigator, "connection", { value: { effectiveType: "4g" }, configurable: true });
    expect(savesData()).toBe(false);
  });
});
