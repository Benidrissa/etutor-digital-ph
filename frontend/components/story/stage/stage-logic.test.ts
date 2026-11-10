/**
 * The cartoon stage's pure logic (#2673): who stands on stage, which picture
 * each pose uses, what a placeholder looks like, and which set a place gets.
 */

import { describe, expect, it } from "vitest";

import type { CastMember, Chapter, StoryCourse } from "@/lib/story-course/types";

import {
  artFor,
  buildActors,
  genderIn,
  heroVariants,
  lookFor,
  poseFor,
  safeArtUrl,
  slotsFor,
  stageOrder,
  voiceProfileOf,
  GROUND,
} from "./cast";
import { placeTheme, placeTitle, skyFor } from "./places";
import { bubbleBox } from "./panels";
import { planSteps, presenterOf, reactorOf } from "./scene-plan";

const OLD_CAST: CastMember[] = [
  { id: "margo", name: "Margo", kind: "ai_tutor", art: "margo" },
  { id: "mentor", name: "M. Kaboré", kind: "adult", art: "mr_kabore" },
  { id: "peer", name: "Awa", kind: "child", art: "friend" },
];

const CONTRACT_CAST: CastMember[] = [
  {
    id: "hero",
    role: "hero",
    name: "{child}",
    kind: "child",
    art: "hero",
    variants: [{ id: "girl" }, { id: "boy" }],
  },
  { id: "friend", role: "friend", name: "{friend}", default_name: "Awa", kind: "child", art: "friend" },
  { id: "mentor", role: "mentor", name: "Mme Ouédraogo", kind: "adult", art: "teacher", voice: { pitch: 0.9, rate: 0.9 } },
  { id: "margo", role: "tutor", name: "Margo", kind: "ai_tutor", art: "margo" },
];

function course(cast: CastMember[]): Pick<StoryCourse, "cast" | "learner"> {
  return { cast, learner: { first_name: "{child}" } };
}

describe("cast", () => {
  it("renders the older ids: mentor, peer and margo", () => {
    const actors = buildActors(course(OLD_CAST), undefined);
    expect([...actors.keys()]).toEqual(["margo", "mentor", "peer"]);
    expect(actors.get("margo")).toMatchObject({ figure: "gecko", isTutor: true, artKey: "margo" });
    expect(actors.get("mentor")).toMatchObject({ figure: "adult", isMentor: true, isHero: false });
    expect(actors.get("peer")).toMatchObject({ figure: "child", isHero: false });
  });

  it("keys the hero's pictures by the chosen variant", () => {
    const actors = buildActors(course(CONTRACT_CAST), "boy");
    expect(actors.get("hero")).toMatchObject({ isHero: true, artKey: "hero:boy", figure: "child" });
    expect(actors.get("hero")?.look.feminine).toBe(false);
    expect(buildActors(course(CONTRACT_CAST), "girl").get("hero")?.look.feminine).toBe(true);
    // A variant the hero does not offer is ignored.
    expect(buildActors(course(CONTRACT_CAST), "dragon").get("hero")?.artKey).toBe("hero");
  });

  it("offers the hero's variants only when there is a choice", () => {
    expect(heroVariants(course(CONTRACT_CAST))).toEqual(["girl", "boy"]);
    expect(heroVariants(course(OLD_CAST))).toEqual([]);
  });

  it("finds the hero by name in a hand-written week", () => {
    const actors = buildActors(
      { cast: [{ id: "nandi", name: "Nandi", kind: "child", art: "nandi" }], learner: { first_name: "Nandi" } },
      undefined,
    );
    expect(actors.get("nandi")?.isHero).toBe(true);
  });

  it("uses the cast's voice, clamped, and a default per figure", () => {
    const actors = buildActors(course(CONTRACT_CAST), "girl");
    expect(actors.get("mentor")?.voice).toMatchObject({ pitch: 0.9, rate: 0.9 });
    expect(actors.get("margo")?.voice.pitch).toBeGreaterThan(1);
    const loud = buildActors(
      course([{ id: "x", name: "X", kind: "adult", art: "x", voice: { pitch: 9, rate: -1 } }]),
      undefined,
    );
    expect(loud.get("x")?.voice).toMatchObject({ pitch: 2, rate: 0.5 });
  });

  it("gives each cast member an AI voice: Margo, a child or an adult, by gender (#2704)", () => {
    const girl = buildActors(course(CONTRACT_CAST), "girl");
    expect(girl.get("hero")?.voice.profile).toBe("girl");
    expect(girl.get("margo")?.voice.profile).toBe("tutor");
    expect(girl.get("mentor")?.voice.profile).toBe(girl.get("mentor")?.look.feminine ? "woman" : "man");
    expect(buildActors(course(CONTRACT_CAST), "boy").get("hero")?.voice.profile).toBe("boy");
    expect(voiceProfileOf("adult", { feminine: true }, false)).toBe("woman");
    expect(voiceProfileOf("adult", { feminine: false }, false)).toBe("man");
    expect(voiceProfileOf("child", { feminine: false }, true)).toBe("tutor");
    expect(voiceProfileOf("gecko", { feminine: true }, false)).toBe("tutor");
  });

  it("reads a look sentence for the placeholder", () => {
    const look = lookFor({
      id: "nurse",
      name: "Fatou",
      kind: "adult",
      art: "nurse",
      look: "A woman in her thirties with glasses, a purple head wrap and a white coat over a green dress.",
    });
    expect(look.feminine).toBe(true);
    expect(look.hairStyle).toBe("wrap");
    expect(look.bottomStyle).toBe("dress");
    expect(look.accessories).toEqual(expect.arrayContaining(["glasses", "coat"]));
    expect(look.bottom).toBe("#2f9e5b");
  });

  it("lets the cast's look decide over an old art key drawn as the other gender", () => {
    // The bible gives the friend the girl preset's art key; the model wrote a boy.
    const boy = lookFor({
      id: "friend",
      name: "{friend}",
      kind: "child",
      art: "friend",
      look: "an 11-year-old boy, short hair, green shirt and khaki shorts",
    });
    expect(boy.feminine).toBe(false);
    // Nothing of the girl preset is carried over.
    expect(boy.accessories).not.toContain("headband");
    expect(boy.hairStyle).not.toBe("braids");
    expect(boy.bottomStyle).toBe("shorts");
    // And the other way round: no beard on a woman drawn from Papa Ben's key.
    const woman = lookFor({ id: "family", name: "Mariam", kind: "adult", art: "papa_ben", look: "a grandmother with a head wrap" });
    expect(woman.feminine).toBe(true);
    expect(woman.accessories).not.toContain("beard");
    // A look that says nothing about gender keeps the preset.
    expect(lookFor({ id: "friend", name: "{friend}", kind: "child", art: "friend", look: "round face, orange top" }).feminine).toBe(true);
  });

  it("gives the same placeholder look on every visit", () => {
    const member: CastMember = { id: "peer", name: "Awa", kind: "child", art: "kid" };
    expect(lookFor(member)).toEqual(lookFor(member));
  });

  it("is not fooled by a word about someone else, or a letter that looks like a title (#2682)", () => {
    // "his daughter" is about her father: the person is a man.
    expect(genderIn("a tall man holding his daughter's hand")).toBe(false);
    // "her" is the person herself.
    expect(genderIn("smiles with her friends")).toBe(true);
    // A bare "m" in a size or a word is no "M." title.
    expect(genderIn("1.5 m tall, round face, orange top")).toBeUndefined();
    expect(genderIn("a mango in hand")).toBeUndefined();
    // So the girl preset of the friend's art key stands.
    const friend = lookFor({ id: "friend", name: "{friend}", kind: "child", art: "friend", look: "1.5 m tall, round face" });
    expect(friend.feminine).toBe(true);
    // A title in front of the name still says who is meant.
    expect(lookFor({ id: "teacher", name: "M. Sanou", kind: "adult", art: "teacher" }).feminine).toBe(false);
    expect(lookFor({ id: "nurse", name: "Mme Traoré", kind: "adult", art: "nurse" }).feminine).toBe(true);
  });

  it("dresses everyone differently, the hero and the friend above all (#2682)", () => {
    // Two girls whose presets are the same white top, blue skirt and headband.
    const cast: CastMember[] = [
      { id: "hero", role: "hero", name: "Aminata", kind: "child", art: "nandi" },
      { id: "friend", role: "friend", name: "Awa", kind: "child", art: "friend" },
      { id: "mentor", role: "mentor", name: "M. Kaboré", kind: "adult", art: "mr_kabore" },
      { id: "family", role: "family", name: "Maman", kind: "adult", art: "maman_olivia" },
    ];
    const actors = buildActors(course(cast), undefined);
    const hero = actors.get("hero")!.look;
    const friend = actors.get("friend")!.look;
    expect(friend.top).not.toBe(hero.top);
    expect(friend.bottomStyle).not.toBe(hero.bottomStyle);
    // Every top differs from every other one.
    const tops = [...actors.values()].map((actor) => actor.look.top);
    expect(new Set(tops).size).toBe(tops.length);
    // The same story dresses them the same way every time.
    expect(buildActors(course(cast), undefined).get("friend")!.look).toEqual(friend);
  });

  it("keeps the hero's outfit and moves the others off it (#2682)", () => {
    const actors = buildActors(course(CONTRACT_CAST), "girl");
    const before = lookFor(CONTRACT_CAST[0], "girl");
    expect(actors.get("hero")!.look.top).toBe(before.top);
    for (const id of ["friend", "mentor"]) expect(actors.get(id)!.look.top).not.toBe(before.top);
  });

  it("maps every mood to a pose, unknown ones to talking", () => {
    expect(poseFor("happy", true)).toBe("happy");
    expect(poseFor("dancing", true)).toBe("talk");
    expect(poseFor(undefined, false)).toBe("idle");
  });
});

describe("art", () => {
  const art = {
    characters: {
      "hero:girl": { idle: "/api/v1/story-art/1/data", talk: "/api/v1/story-art/2/data" },
      mentor: { idle: "javascript:alert(1)" },
    },
  };

  it("picks the pose's picture, else the nearest one", () => {
    expect(artFor(art, "hero:girl", "talk")).toBe("/api/v1/story-art/2/data");
    // No happy picture: talking is the nearest, then idle.
    expect(artFor(art, "hero:girl", "happy")).toBe("/api/v1/story-art/2/data");
    expect(artFor(art, "hero:girl", "think")).toBe("/api/v1/story-art/1/data");
    expect(artFor(art, "hero:girl", "sad")).toBe("/api/v1/story-art/1/data");
  });

  it("falls back to the placeholder for a missing key or an unsafe URL", () => {
    expect(artFor(art, "friend", "idle")).toBeUndefined();
    expect(artFor(art, "mentor", "idle")).toBeUndefined();
    expect(artFor(undefined, "hero:girl", "idle")).toBeUndefined();
  });

  it("accepts same-origin paths, https and image data URLs only", () => {
    expect(safeArtUrl("/api/v1/story-art/x/data")).toBe("/api/v1/story-art/x/data");
    expect(safeArtUrl("https://cdn.example.org/a.webp")).toBe("https://cdn.example.org/a.webp");
    expect(safeArtUrl("data:image/webp;base64,AAAA")).toBe("data:image/webp;base64,AAAA");
    expect(safeArtUrl("//evil.example/a.png")).toBeUndefined();
    expect(safeArtUrl("http://plain.example/a.png")).toBeUndefined();
    expect(safeArtUrl("data:text/html;base64,AAAA")).toBeUndefined();
    expect(safeArtUrl(42)).toBeUndefined();
  });
});

describe("speech bubbles", () => {
  it("sits beside an edge speaker's head when nobody stands in the way", () => {
    const box = bubbleBox({ x: 15, height: 42 }, [{ x: 85, height: 50 }]);
    expect(box.left).toBeGreaterThan(15);
    expect(box.bottom).toBeLessThan(GROUND + 42 + 1);
  });

  it("stays beside an edge speaker's head when it only passes over someone's shoulder (#2682)", () => {
    // The friend speaks from the left; the hero stands at the right edge.
    // The bubble reaches past the hero's arm but not their face.
    const box = bubbleBox({ x: 17, height: 42 }, [{ x: 83, height: 42 }]);
    expect(box.bottom).toBeLessThan(GROUND + 42);
    // Over a face it does rise.
    const over = bubbleBox({ x: 17, height: 42 }, [{ x: 60, height: 42 }]);
    expect(over.bottom).toBeGreaterThanOrEqual(GROUND + 42 + 3);
  });

  it("does not rise for someone whose head is below it already", () => {
    // A small tutor under a tall speaker's bubble.
    const box = bubbleBox({ x: 17, height: 50 }, [{ x: 50, height: 22 }]);
    expect(box.bottom).toBeLessThan(GROUND + 50);
  });

  it("rises above the face of anyone it would cover", () => {
    // Margo speaks from the right; the hero stands in the middle.
    const box = bubbleBox({ x: 85, height: 22 }, [
      { x: 15, height: 50 },
      { x: 50, height: 42 },
    ]);
    expect(box.bottom).toBeGreaterThanOrEqual(GROUND + 42 + 3);
    expect(box.left + box.width).toBeLessThan(85);
  });
});

describe("layout", () => {
  it("spreads one to four people across the stage", () => {
    expect(slotsFor(1)).toHaveLength(1);
    expect(slotsFor(3)).toEqual([15, 50, 85]);
    for (const x of slotsFor(4)) {
      expect(x).toBeGreaterThan(5);
      expect(x).toBeLessThan(95);
    }
  });

  it("puts the hero on the left and Margo on the right", () => {
    const actors = buildActors(course(CONTRACT_CAST), "girl");
    expect(stageOrder(["margo", "mentor", "hero", "ghost", "mentor"], actors)).toEqual(["hero", "mentor", "margo"]);
  });
});

describe("scene plan", () => {
  const chapters: Chapter[] = [
    {
      id: "ch1",
      title: { en: "One", fr: "Un" },
      scenes: [
        {
          id: "s1",
          place: "market",
          cast: ["mentor", "hero"],
          steps: [
            { type: "narrate", en: "At the market.", fr: "Au marché." },
            { type: "say", who: "friend", en: "Hi!", fr: "Salut !" },
          ],
        },
        // Nobody speaks here: the people of the scene before stay on.
        { id: "s2", place: "market", steps: [{ type: "concept", en: ["Row"], fr: ["Ligne"] }] },
        { id: "s3", place: "classroom", steps: [{ type: "ask", ref: "q1" }] },
      ],
    },
    {
      id: "ch2",
      title: { en: "Two", fr: "Deux" },
      scenes: [{ id: "s4", place: "classroom", steps: [{ type: "narrate", en: "Later.", fr: "Plus tard." }] }],
    },
  ];
  const actors = buildActors(course(CONTRACT_CAST), "girl");

  it("lists every step with its chapter, scene and cast", () => {
    const plan = planSteps(chapters, chapters, actors);
    expect(plan.map((item) => item.sceneId)).toEqual(["s1", "s1", "s2", "s3", "s4"]);
    expect(plan[0].cast).toEqual(["hero", "mentor", "friend"]);
    expect(plan[2].cast).toEqual(plan[0].cast);
    expect(plan.map((item) => item.startsChapter)).toEqual([true, false, false, false, true]);
    expect(plan.map((item) => item.chapterNumber)).toEqual([1, 1, 1, 1, 2]);
  });

  it("starts a new place run on a new place or a new chapter only", () => {
    const plan = planSteps(chapters, chapters, actors);
    expect(plan.map((item) => item.placeRun)).toEqual([0, 0, 0, 3, 4]);
  });

  it("numbers a chapter played on its own by its place in the story", () => {
    const plan = planSteps([chapters[1]], chapters, actors);
    expect(plan[0].chapterNumber).toBe(2);
    // No speaker and nothing before: the teacher and the hero.
    expect(plan[0].cast).toEqual(["hero", "mentor"]);
  });

  it("names the hero to react and the teacher to present", () => {
    expect(reactorOf(["hero", "mentor"], actors)).toBe("hero");
    expect(reactorOf(["mentor", "friend"], actors)).toBe("mentor");
    expect(presenterOf(["hero", "friend", "mentor"], actors)).toBe("mentor");
  });
});

describe("places", () => {
  it("knows the older catalog's places", () => {
    expect(placeTheme("mango_farm")).toBe("farm");
    expect(placeTheme("school_yard")).toBe("yard");
    expect(placeTheme("classroom")).toBe("classroom");
  });

  it("reads an adult course's place from its id and look", () => {
    expect(placeTheme("district_health_centre")).toBe("clinic");
    expect(placeTheme("team_office")).toBe("office");
    expect(placeTheme("p3", "A busy open-air market with fruit stalls")).toBe("market");
  });

  it("varies an unknown place by its id, the same way every time", () => {
    expect(["savanna", "village"]).toContain(placeTheme("xyz"));
    expect(placeTheme("xyz")).toBe(placeTheme("xyz"));
    expect(skyFor("xyz")).toBe(skyFor("xyz"));
  });

  it("titles a place from the course, else the catalog", () => {
    const places = { places: [{ id: "market", title: { en: "Rood Woko", fr: "Rood Woko" } }] };
    expect(placeTitle(places, "market")).toEqual({ en: "Rood Woko", fr: "Rood Woko" });
    expect(placeTitle({}, "market")?.fr).toBe("Au marché");
    expect(placeTitle({}, "nowhere")).toBeUndefined();
  });
});
