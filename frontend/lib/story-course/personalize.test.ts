/**
 * Tests for the {child}/{friend} substitution (contract C4).
 *
 * The promise under test: every string the learner can see gets their name,
 * the cached document is never touched, and an unknown name falls back to a
 * word in the language of the sentence it lands in.
 */

import { describe, expect, it } from "vitest";

import { NAME_FALLBACKS, firstNameOf, personalizeStory } from "./personalize";

/** A cut-down lesson story touching every kind of place a name can sit. */
function sampleStory() {
  return {
    format: "story-course/1",
    id: "lesson-abc-fr",
    title: { en: "{child} and the cold chain", fr: "{child} et la chaîne du froid" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "{child}" },
    cast: [
      { id: "learner", name: "{child}", kind: "adult", art: "nandi" },
      { id: "friend", name: "Kofi", kind: "adult", art: "friend" },
    ],
    chapters: [
      {
        id: "c1",
        title: { en: "Morning", fr: "Le matin" },
        scenes: [
          {
            id: "s1",
            place: "classroom",
            steps: [
              { type: "narrate", en: "{child} opens the fridge.", fr: "{child} ouvre le frigo." },
              { type: "say", who: "friend", en: "{child}, check it!", fr: "{child}, vérifie !" },
              {
                type: "concept",
                title: { en: "Why", fr: "Pourquoi" },
                en: ["{friend} reads the log.", "No name here."],
                fr: ["{friend} lit le relevé.", "Aucun nom ici."],
              },
            ],
          },
        ],
      },
    ],
    questions: [
      {
        id: "q1",
        type: "choice",
        prompt: { en: "What does {child} do?", fr: "Que fait {child} ?" },
        answer: "a",
        choices: [
          { id: "a", en: "{child} records it", fr: "{child} le note" },
          { id: "b", en: "Ignore it", fr: "L'ignorer", misconception: "m1" },
        ],
        hints: [{ en: "Think, {child}.", fr: "Réfléchis, {child}." }],
      },
    ],
    minigames: [
      {
        id: "g1",
        engine: "catch",
        rounds: [
          {
            prompt: { en: "Help {child}", fr: "Aide {child}" },
            items: [{ label: { en: "{child}'s log", fr: "Le relevé de {child}" }, correct: true }],
          },
        ],
      },
    ],
    checks: { max_points: 3 },
  };
}

describe("personalizeStory", () => {
  it("replaces {child} in every string, however deep", () => {
    const out = personalizeStory(sampleStory(), { child: "Aminata", language: "fr" });

    expect(out.title).toEqual({ en: "Aminata and the cold chain", fr: "Aminata et la chaîne du froid" });
    expect(out.learner.first_name).toBe("Aminata");
    expect(out.cast[0].name).toBe("Aminata");
    const steps = out.chapters[0].scenes[0].steps;
    expect(steps[0].en).toBe("Aminata opens the fridge.");
    expect(steps[0].fr).toBe("Aminata ouvre le frigo.");
    expect(steps[1].fr).toBe("Aminata, vérifie !");
    expect(out.questions[0].prompt.fr).toBe("Que fait Aminata ?");
    expect(out.questions[0].choices[0]).toMatchObject({ en: "Aminata records it", fr: "Aminata le note" });
    expect(out.questions[0].hints[0].en).toBe("Think, Aminata.");
    expect(out.minigames[0].rounds[0].items[0].label.fr).toBe("Le relevé de Aminata");
    // Nothing left behind anywhere in the document.
    expect(JSON.stringify(out)).not.toContain("{child}");
  });

  it("takes {friend} from the story's own cast", () => {
    const out = personalizeStory(sampleStory(), { child: "Aminata", language: "fr" });
    const concept = out.chapters[0].scenes[0].steps[2];
    expect(concept.en).toEqual(["Kofi reads the log.", "No name here."]);
    expect(concept.fr).toEqual(["Kofi lit le relevé.", "Aucun nom ici."]);
  });

  it("does not mutate the cached document", () => {
    const original = sampleStory();
    const snapshot = JSON.stringify(original);
    const out = personalizeStory(original, { child: "Aminata", language: "fr" });

    expect(JSON.stringify(original)).toBe(snapshot);
    expect(out).not.toBe(original);
    expect(out.chapters).not.toBe(original.chapters);
    expect(out.chapters[0].scenes[0].steps[0]).not.toBe(original.chapters[0].scenes[0].steps[0]);
  });

  it("falls back per language when the name is unknown", () => {
    const out = personalizeStory(sampleStory(), { child: null, language: "fr" });
    const step = out.chapters[0].scenes[0].steps[0];

    // English text gets the English word, French text the French one...
    expect(step.en).toBe(`${NAME_FALLBACKS.child.en} opens the fridge.`);
    expect(step.fr).toBe(`${NAME_FALLBACKS.child.fr} ouvre le frigo.`);
    // ...and strings outside an en/fr key use the reading language.
    expect(out.learner.first_name).toBe(NAME_FALLBACKS.child.fr);
    expect(out.cast[0].name).toBe(NAME_FALLBACKS.child.fr);
  });

  it("uses an epicene French fallback, keeping the French gender-neutral", () => {
    expect(NAME_FALLBACKS.child.fr).toBe("Élève");
    expect(NAME_FALLBACKS.friend.fr).toBe("Camarade");
  });

  it("falls back for {friend} when the cast names no classmate", () => {
    const story = sampleStory();
    story.cast = story.cast.filter((member) => member.id !== "friend");
    const out = personalizeStory(story, { child: "Aminata", language: "en" });
    const concept = out.chapters[0].scenes[0].steps[2];
    expect(concept.en[0]).toBe(`${NAME_FALLBACKS.friend.en} reads the log.`);
    expect(concept.fr[0]).toBe(`${NAME_FALLBACKS.friend.fr} lit le relevé.`);
  });

  it("treats a name as data, not as a replacement pattern", () => {
    const out = personalizeStory(sampleStory(), { child: "A$&b", language: "en" });
    expect(out.learner.first_name).toBe("A$&b");
  });

  it("leaves non-string values alone", () => {
    const out = personalizeStory(sampleStory(), { child: "Aminata", language: "en" });
    expect(out.checks.max_points).toBe(3);
    expect(out.minigames[0].rounds[0].items[0].correct).toBe(true);
  });
});

describe("firstNameOf", () => {
  it.each([
    ["Aminata Diallo", "Aminata"],
    ["  Kofi  ", "Kofi"],
    ["Marie-Claire Ouédraogo", "Marie-Claire"],
    ["Dr. Awa Traoré", "Awa"],
    ["Mme Fatou Sow", "Fatou"],
  ])("reads %j as %j", (input, expected) => {
    expect(firstNameOf(input)).toBe(expected);
  });

  it.each([null, undefined, "", "   ", "amina@example.org", "1234"])(
    "returns null for %j",
    (input) => {
      expect(firstNameOf(input)).toBeNull();
    },
  );
});
