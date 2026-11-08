/**
 * Personalising a cached lesson story for the learner reading it (contract C4).
 *
 * A lesson story is generated once per unit and language and then served to
 * every learner, so the stored document never carries a real name. Wherever
 * the learner appears it says `{child}` (and a classmate, when the story has
 * one, `{friend}`); `learner.first_name` is itself the literal `{child}`. The
 * client swaps the real first name in just before rendering.
 *
 * The substitution runs on a copy. The original document is what sits in the
 * IndexedDB cache and in React state, and it must stay name-free: the same
 * cached story is reused when another learner signs in on a shared phone.
 */

import type { StoryCourse } from "./types";

export type StoryLanguage = "en" | "fr";

/**
 * Stand-ins for a name we do not know, per language of the string they land in.
 *
 * They read as a name in both positions a story uses one — as a subject
 * ("Learner checks the register.") and when addressed ("Well done, Learner!")
 * — which a pronoun cannot do. The French words are epicene (one form for any
 * gender), so the fallback keeps the story's gender-neutral French intact.
 */
export const NAME_FALLBACKS: Record<"child" | "friend", Record<StoryLanguage, string>> = {
  child: { en: "Learner", fr: "Élève" },
  friend: { en: "Classmate", fr: "Camarade" },
};

/** Titles people put in front of their name at sign-up. */
const HONORIFICS = new Set([
  "dr",
  "mr",
  "mrs",
  "ms",
  "miss",
  "pr",
  "prof",
  "m",
  "mme",
  "mlle",
  "me",
]);

const PLACEHOLDER = /\{(child|friend)\}/g;
const HAS_LETTER = /\p{L}/u;
/** Leading/trailing characters that are not letters ("Dr.", "(Awa)", "Kofi,"). */
const EDGE_PUNCTUATION = /^[^\p{L}]+|[^\p{L}]+$/gu;

/**
 * The first name to address a learner by, from the free-text `name` they gave
 * at sign-up, or null when it cannot be read as a name.
 *
 * "Dr Aminata Diallo" -> "Aminata"; "Marie-Claire Ouédraogo" -> "Marie-Claire";
 * an email address, or a string with no letters at all, -> null.
 */
export function firstNameOf(fullName: string | null | undefined): string | null {
  if (!fullName) return null;
  const trimmed = fullName.trim();
  if (!trimmed || trimmed.includes("@")) return null;

  const tokens = trimmed
    .split(/\s+/)
    .map((token) => token.replace(EDGE_PUNCTUATION, ""))
    .filter((token) => HAS_LETTER.test(token));
  const name = tokens.find((token) => !HONORIFICS.has(token.toLowerCase()));
  // A name made only of honorifics ("Dr") is better than nothing.
  return name ?? tokens[0] ?? null;
}

export interface PersonalizeOptions {
  /** The learner's first name; null/undefined uses the fallback. */
  child?: string | null;
  /** The classmate's name; defaults to the story's own cast, then the fallback. */
  friend?: string | null;
  /**
   * Language for strings that are not inside an `en`/`fr` key (cast names,
   * `learner.first_name`): the language the story is being read in.
   */
  language: StoryLanguage;
}

/**
 * A copy of `doc` with `{child}` and `{friend}` replaced in every string.
 *
 * The walk tracks the nearest `en`/`fr` key above each string, because a
 * fallback name must be in the language of the sentence it lands in, not the
 * language of the interface: an English learner reading the French line
 * beneath sees "Élève", not "Learner".
 */
export function personalizeStory<T>(doc: T, options: PersonalizeOptions): T {
  const child = cleanName(options.child);
  const friend = cleanName(options.friend) ?? castFriendName(doc);

  const nameFor = (placeholder: string, lang: StoryLanguage): string => {
    if (placeholder === "child") return child ?? NAME_FALLBACKS.child[lang];
    return friend ?? NAME_FALLBACKS.friend[lang];
  };

  const walk = (value: unknown, lang: StoryLanguage): unknown => {
    if (typeof value === "string") {
      if (!value.includes("{")) return value;
      // A replacer function, not a replacement string: a name is data, and a
      // `$&` in it must not be read as a pattern.
      return value.replace(PLACEHOLDER, (_match, which: string) => nameFor(which, lang));
    }
    if (Array.isArray(value)) return value.map((item) => walk(item, lang));
    if (isPlainObject(value)) {
      const out: Record<string, unknown> = {};
      for (const [key, inner] of Object.entries(value)) {
        out[key] = walk(inner, key === "en" || key === "fr" ? key : lang);
      }
      return out;
    }
    return value;
  };

  return walk(doc, options.language) as T;
}

function cleanName(name: string | null | undefined): string | null {
  const trimmed = name?.trim();
  return trimmed ? trimmed : null;
}

/** The classmate's name when the story's cast gives one (not a placeholder). */
function castFriendName(doc: unknown): string | null {
  if (!isPlainObject(doc)) return null;
  const cast = (doc as Partial<StoryCourse>).cast;
  if (!Array.isArray(cast)) return null;
  const friend = cast.find((member) => member?.id === "friend" || member?.art === "friend");
  const name = friend?.name?.trim();
  return name && !name.includes("{") ? name : null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}
