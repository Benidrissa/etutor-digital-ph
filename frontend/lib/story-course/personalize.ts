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

import type { CastMember, StoryCourse } from "./types";

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
  /**
   * Placeholders to leave as they are, for a later pass. The module story
   * panel fills `{child}` and keeps `{friend}`: the player asks the learner
   * for the friend's name at the start of the story and fills it in itself.
   */
  keep?: ReadonlyArray<"child" | "friend">;
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
  const keep = new Set<string>(options.keep ?? []);

  const nameFor = (placeholder: string, lang: StoryLanguage): string => {
    if (placeholder === "child") return child ?? NAME_FALLBACKS.child[lang];
    return friend ?? NAME_FALLBACKS.friend[lang];
  };

  const walk = (value: unknown, lang: StoryLanguage): unknown => {
    if (typeof value === "string") {
      if (!value.includes("{")) return value;
      // A replacer function, not a replacement string: a name is data, and a
      // `$&` in it must not be read as a pattern.
      return value.replace(PLACEHOLDER, (match, which: string) =>
        keep.has(which) ? match : nameFor(which, lang),
      );
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

/**
 * The classmate's name when the story's cast gives one: their own name, or,
 * when that is the `{friend}` placeholder, the cast's `default_name` (#2672).
 */
export function castFriendName(doc: unknown): string | null {
  const friend = castFriend(doc);
  const name = friend?.name?.trim();
  if (name && !name.includes("{")) return name;
  const fallback = friend?.default_name?.trim();
  return fallback && !fallback.includes("{") ? fallback : null;
}

/**
 * True when the story leaves the friend's name to the learner: it says
 * `{friend}` somewhere and its cast does not name the friend outright (a
 * `default_name` is only what a learner who types nothing gets).
 */
export function asksFriendName(doc: unknown): boolean {
  const friend = castFriend(doc);
  const name = friend?.name?.trim();
  if (name && !name.includes("{")) return false;
  return JSON.stringify(doc ?? null).includes("{friend}");
}

function castFriend(doc: unknown): Partial<CastMember> | undefined {
  if (!isPlainObject(doc)) return undefined;
  const cast = (doc as Partial<StoryCourse>).cast;
  if (!Array.isArray(cast)) return undefined;
  return (
    cast.find((member) => member?.role === "friend") ??
    cast.find((member) => member?.id === "friend" || member?.art === "friend")
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}
