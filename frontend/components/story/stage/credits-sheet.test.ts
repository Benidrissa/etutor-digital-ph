import { describe, expect, it } from "vitest";

import type { StoryCourse } from "@/lib/story-course/types";

import { creditsFor } from "./credits-sheet";

const ID = "0f6b8a2e-1c3d-4e5f-8a9b-0c1d2e3f4a5b";
const URL = `/api/v1/story-props/${ID}/data`;

function story(props: StoryCourse["props"], media: NonNullable<StoryCourse["art"]>["props"]): StoryCourse {
  return { props, art: { status: "none", characters: {}, places: {}, props: media } } as unknown as StoryCourse;
}

const basket = {
  id: "basket",
  label: { en: "the basket", fr: "le panier" },
  query: "woven straw basket",
  kind: "sticker" as const,
};

describe("creditsFor and the shared 3D prop library", () => {
  it("credits a library sticker to its 3D model, not to an AI drawing", () => {
    const entries = creditsFor(
      story([basket], {
        basket: {
          sticker: URL,
          picture: {
            src: URL,
            width: 300,
            height: 280,
            alt: { en: "the basket", fr: "le panier" },
            via: "open_3d",
            credit: {
              kind: "web",
              author: "Quaternius",
              license: "CC0-1.0",
              text: { en: "3D model: Quaternius (CC0 1.0)", fr: "Modèle 3D : Quaternius (CC0 1.0)" },
            },
          },
        },
      }),
      "en",
    );
    expect(entries.map((entry) => entry.credit.kind)).toEqual(["web"]);
    expect(entries[0].credit.text.en).toContain("Quaternius");
    expect(entries[0].label).toBe("the basket");
  });

  it("still credits an AI sticker as a drawing made with AI", () => {
    const entries = creditsFor(story([basket], { basket: { sticker: URL } }), "en");
    expect(entries.map((entry) => entry.key)).toEqual(["generated"]);
  });
});

describe("creditsFor and lesson illustrations (#2709)", () => {
  const illustration = "22222222-2222-4222-8222-222222222222";
  const figure = "65bb9ff9-1111-4111-8111-111111111111";

  it("credits a course figure to the course and an illustration to the course, made with AI", () => {
    const entries = creditsFor(
      {
        props: [
          {
            id: "poster",
            kind: "figure",
            label: { en: "the poster", fr: "l'affiche" },
            query: "poster",
            figure: { source_image_id: figure, figure_number: "Figure 1.2" },
          },
          {
            id: "sketch",
            kind: "figure",
            label: { en: "the sketch", fr: "le croquis" },
            query: "sketch",
            figure: { generated_image_id: illustration },
          },
        ],
        chapters: [
          {
            id: "ch1",
            scenes: [
              { id: "s1", steps: [{ type: "show", visual: "image", params: { generated_image_id: illustration } }] },
            ],
          },
        ],
        art: { status: "none", characters: {}, places: {}, props: {} },
      } as unknown as StoryCourse,
      "fr",
    );
    // The same illustration, named by a prop and by a show step, is credited once.
    expect(entries.map((entry) => entry.credit.kind)).toEqual(["course", "course_illustration"]);
    expect(entries[0].credit.text.fr).toBe("Tiré du cours · Figure 1.2");
    expect(entries[1].credit.text).toEqual({
      en: "Course illustration (AI)",
      fr: "Illustration du cours (IA)",
    });
  });

  it("credits an illustration shown by a step alone", () => {
    const entries = creditsFor(
      {
        props: [],
        chapters: [
          {
            id: "ch1",
            scenes: [
              { id: "s1", steps: [{ type: "show", visual: "image", params: { generated_image_id: illustration } }] },
            ],
          },
        ],
      } as unknown as StoryCourse,
      "en",
    );
    expect(entries).toHaveLength(1);
    expect(entries[0].credit.kind).toBe("course_illustration");
  });
});
