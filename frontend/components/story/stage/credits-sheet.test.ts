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
