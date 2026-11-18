/**
 * Props (#2681): where a prop stands, which props are on stage at each step,
 * how each is drawn and what its close-up shows.
 */

import { describe, expect, it, vi } from "vitest";

import type { CastMember, Chapter, Prop, PropMedia, Step } from "@/lib/story-course/types";

import { buildActors } from "./cast";
import {
  MAX_FOREGROUND,
  PROP_HEIGHT,
  emojiDrawn,
  layoutProps,
  licenseLabel,
  pictureFor,
  placementOf,
  planSceneProps,
  sameOriginMedia,
  sizeOf,
  tokenFor,
  type OnStageProp,
} from "./props";
import { planSteps } from "./scene-plan";

const PROPS: Prop[] = [
  { id: "pebble", label: { en: "a pebble", fr: "un caillou" }, query: "river pebble", kind: "sticker", emoji: "🪨", at: "ground", size: "s" },
  { id: "snail", label: { en: "a snail", fr: "un escargot" }, query: "garden snail", kind: "real", educational: true, emoji: "🐌", at: "ground", size: "s" },
  { id: "tree", label: { en: "the néré tree", fr: "le néré" }, query: "Parkia biglobosa tree", kind: "real", emoji: "🌳", at: "back", size: "l" },
  { id: "basket", label: { en: "a basket", fr: "un panier" }, query: "woven basket", kind: "sticker", emoji: "🧺", at: "held", holder: "family", size: "m" },
  { id: "cup", label: { en: "a cup", fr: "une tasse" }, query: "tin cup", kind: "sticker", at: "table" },
  {
    id: "cells",
    label: { en: "onion skin cells", fr: "des cellules d'oignon" },
    query: "onion epidermis cells microscope",
    kind: "figure",
    at: "table",
    figure: { source_image_id: "3f2c9a1e-0b7d-4c55-9e2a-1d2f3a4b5c6d", figure_number: "Figure 1.4", attribution: "OpenStax, CC BY 4.0" },
  },
];
const KNOWN = new Map(PROPS.map((prop) => [prop.id, prop]));
const get = (id: string) => KNOWN.get(id)!;

const say = (props: string[]): Step => ({ type: "say", who: "hero", en: "…", fr: "…", props });
const closeUp = (id: string): Step => ({ type: "show", visual: "prop", params: { prop: id } });

describe("placement and size", () => {
  it("puts a held prop down when its holder is off stage", () => {
    expect(placementOf(get("basket"), ["family"])).toBe("held");
    expect(placementOf(get("basket"), ["hero"])).toBe("ground");
  });

  it("makes held props small and keeps large for scenery only", () => {
    expect(sizeOf(get("basket"), "held")).toBe("s");
    expect(sizeOf({ ...get("snail"), size: "l" }, "ground")).toBe("m");
    expect(sizeOf(get("tree"), "back")).toBe("l");
    expect(sizeOf(get("cup"), "table")).toBe("m");
    expect(PROP_HEIGHT).toEqual({ s: 15, m: 22, l: 64 });
  });
});

describe("layout", () => {
  const onStage = (ids: string[], cast: string[]): OnStageProp[] =>
    ids.map((id) => {
      const placement = placementOf(get(id), cast);
      return { prop: get(id), placement, size: sizeOf(get(id), placement) };
    });

  it("stands scenery behind the cast and things in a hand above everyone", () => {
    const slots = layoutProps(onStage(["tree", "basket"], ["hero", "family"]), [
      { id: "hero", x: 30, height: 42 },
      { id: "family", x: 70, height: 50 },
    ]);
    expect(slots.get("tree")).toMatchObject({ z: 1, x: 50, height: 64 });
    expect(slots.get("basket")?.z).toBe(4);
    // In the holder's hand, on the side towards the middle.
    expect(slots.get("basket")!.x).toBeLessThan(70);
  });

  it("puts floor props in the free stretches between the cast, never on a body", () => {
    const standing = [
      { id: "hero", x: 15, height: 42 },
      { id: "friend", x: 50, height: 42 },
      { id: "mentor", x: 85, height: 50 },
    ];
    const slots = layoutProps(onStage(["pebble", "snail"], ["hero", "friend", "mentor"]), standing);
    for (const id of ["pebble", "snail"]) {
      const slot = slots.get(id)!;
      for (const figure of standing) expect(Math.abs(slot.x - figure.x)).toBeGreaterThan(5);
    }
    expect(slots.get("pebble")!.x).not.toBe(slots.get("snail")!.x);
  });

  it("raises a table prop onto its table", () => {
    const slots = layoutProps(onStage(["cup"], ["hero"]), [{ id: "hero", x: 30, height: 42 }]);
    expect(slots.get("cup")).toMatchObject({ onTable: true });
  });
});

describe("which props are on stage", () => {
  it("brings scenery and unnamed props in at the first step, named ones at their first mention", () => {
    const plan = planSceneProps(["tree", "pebble", "snail"], [say(["snail"]), say(["pebble"]), say(["snail"])], KNOWN);
    expect(plan[0]).toEqual({ props: ["tree", "snail"], entering: ["tree", "snail"], pointed: ["snail"] });
    expect(plan[1].entering).toEqual(["pebble"]);
    // Named again: it bounces, it does not pop in again.
    expect(plan[2]).toMatchObject({ entering: [], pointed: ["snail"] });
  });

  it("keeps at most two things in front of the cast, sending off the stalest", () => {
    const plan = planSceneProps(
      ["pebble", "snail", "cup"],
      [say(["pebble"]), say(["snail"]), say(["cup"])],
      KNOWN,
    );
    expect(plan[2].props.filter((id) => id !== "tree")).toHaveLength(MAX_FOREGROUND);
    expect(plan[2].props).toEqual(["snail", "cup"]);
  });

  it("keeps the props of the scene before at the same place, without popping them again", () => {
    const plan = planSceneProps(["snail"], [say(["snail"])], KNOWN, ["tree", "snail"]);
    expect(plan[0]).toMatchObject({ props: ["tree", "snail"], entering: [], pointed: ["snail"] });
  });

  it("ignores props nobody declared", () => {
    const plan = planSceneProps(["ghost"], [say(["ghost", "snail"])], KNOWN);
    expect(plan[0].props).toEqual(["snail"]);
  });
});

describe("the story's plan with props", () => {
  const cast: CastMember[] = [
    { id: "hero", role: "hero", name: "Ami", kind: "child", art: "hero" },
    { id: "friend", role: "friend", name: "Awa", kind: "child", art: "friend" },
  ];
  const actors = buildActors({ cast, learner: { first_name: "Ami" } }, undefined);
  const chapters: Chapter[] = [
    {
      id: "c1",
      title: { en: "One", fr: "Un" },
      scenes: [
        { id: "s1", place: "yard", cast: ["hero"], props: ["tree", "snail", "pebble"], steps: [say(["snail"]), closeUp("snail"), closeUp("pebble")] },
        { id: "s2", place: "yard", cast: ["hero"], props: ["pebble"], steps: [say(["pebble"])] },
        { id: "s3", place: "class", cast: ["hero"], props: ["cup"], steps: [say([])] },
      ],
    },
  ];
  const media: Record<string, PropMedia> = {
    snail: { sticker: "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data" },
  };

  it("drops a close-up with nothing to show", () => {
    const plan = planSteps(chapters, chapters, actors, { props: KNOWN, media });
    // The snail has a sticker (shown large); the pebble has nothing.
    expect(plan.filter((item) => item.step.type === "show")).toHaveLength(1);
  });

  it("carries props over at the same place and starts afresh at a new one", () => {
    const plan = planSteps(chapters, chapters, actors, { props: KNOWN, media });
    const s2 = plan.find((item) => item.sceneId === "s2")!;
    expect(s2.props).toEqual(expect.arrayContaining(["tree", "snail", "pebble"]));
    expect(s2.entering).toEqual([]);
    const s3 = plan.find((item) => item.sceneId === "s3")!;
    expect(s3.props).toEqual(["cup"]);
    expect(s3.entering).toEqual(["cup"]);
  });

  it("still plans a story without props", () => {
    const plan = planSteps(chapters, chapters, actors);
    expect(plan.every((item) => item.props.length === 0)).toBe(true);
    // Without a picture for any prop, both close-ups are dropped.
    expect(plan.some((item) => item.step.type === "show")).toBe(false);
  });
});

describe("tokens and pictures", () => {
  const sticker = "/api/v1/story-props/4aa0b1c2-d3e4-4f5a-8b6c-7d8e9f0a1b2c/data";
  const photo = "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data?size=s";
  const picture = {
    src: photo,
    width: 400,
    height: 300,
    alt: { en: "a snail", fr: "un escargot" },
    via: "open_photo" as const,
    credit: { kind: "web" as const, license: "CC-BY-4.0", text: { en: "by Jane", fr: "par Jane" } },
  };

  it("draws a sticker, else a photo in front of the cast, else the emoji, else the name", () => {
    expect(tokenFor(get("snail"), { sticker, picture }, "ground")).toEqual({ kind: "sticker", src: sticker });
    expect(tokenFor(get("snail"), { picture }, "ground")).toEqual({ kind: "polaroid", src: photo });
    // A photo is never scenery: the tree is its emoji.
    expect(tokenFor(get("tree"), { picture }, "back")).toEqual({ kind: "emoji", emoji: "🌳" });
    expect(tokenFor(get("cup"), undefined, "table")).toEqual({ kind: "label" });
    // A word is not an emoji.
    expect(tokenFor({ ...get("cup"), emoji: "cup" }, undefined, "table")).toEqual({ kind: "label" });
  });

  it("closes up on the served picture, else the course figure, else the sticker", () => {
    expect(pictureFor(get("snail"), { picture }, "fr")?.src).toBe(photo);
    const figure = pictureFor(get("cells"), undefined, "fr")!;
    expect(figure.src).toBe("/api/v1/source-images/3f2c9a1e-0b7d-4c55-9e2a-1d2f3a4b5c6d/data?lang=fr");
    expect(figure.credit.text.fr).toBe("Tiré du cours · Figure 1.4 · OpenStax, CC BY 4.0");
    const drawing = pictureFor(get("pebble"), { sticker }, "en")!;
    expect(drawing).toMatchObject({ src: sticker, via: "ai_drawing" });
    expect(pictureFor(get("pebble"), undefined, "en")).toBeUndefined();
  });

  it("puts only the app's own story media in an image", () => {
    expect(sameOriginMedia(sticker)).toBe(sticker);
    expect(sameOriginMedia(photo)).toBe(photo);
    expect(sameOriginMedia("https://evil.example/x.png")).toBeUndefined();
    expect(sameOriginMedia("/api/v1/users/3f2c9a1e-0b7d/data")).toBeUndefined();
    expect(sameOriginMedia("javascript:alert(1)")).toBeUndefined();
    // A served picture from elsewhere is never used.
    expect(pictureFor(get("snail"), { picture: { ...picture, src: "https://evil.example/x.png" } }, "en")).toBeUndefined();
  });

  it("falls back to the name where the device draws the emoji as an empty box", () => {
    const size = 24 * 24 * 4;
    const box = new Uint8ClampedArray(size);
    box[3] = 255; // one black pixel: the missing character's box
    const colour = new Uint8ClampedArray(size);
    colour.set([200, 120, 40, 255], 0);
    class FakeCanvas {
      getContext() {
        let last = "";
        return {
          font: "",
          textBaseline: "",
          fillStyle: "",
          fillText: (value: string) => {
            last = value;
          },
          getImageData: () => ({ data: last === "🐌" ? colour : box }),
        };
      }
    }
    vi.stubGlobal("OffscreenCanvas", FakeCanvas);
    try {
      expect(emojiDrawn("🐌")).toBe(true);
      expect(emojiDrawn("🪨")).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
    // No canvas to try it on (an old browser): taken as drawn.
    expect(emojiDrawn("🌳")).toBe(true);
  });

  it("writes licences the way a credit line says them", () => {
    expect(licenseLabel("CC-BY-SA-4.0")).toBe("CC BY-SA 4.0");
    expect(licenseLabel("CC0-1.0")).toBe("CC0 1.0");
    expect(licenseLabel("PDM")).toBeUndefined();
  });
});
