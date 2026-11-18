/**
 * Who stands on the cartoon stage, how they look, and which picture to show.
 *
 * The contract (#2672) gives each cast member a `role` and a `look`, and the
 * API attaches generated art keyed by cast id (`hero:<variant>` for the
 * hero) and pose. Stories written before it have neither: ids such as
 * `mentor`, `peer` and `margo`, a `kind` and an old art key. Everything here
 * works from whatever is present, so every story gets a full cast — with
 * generated pictures where they exist and a drawn placeholder where they do
 * not.
 */

import type { CastMember, CastRole, Mood, StoryArt, StoryCourse } from "@/lib/story-course/types";
import type { VoiceProfile } from "./speech";

/** The poses a figure is drawn in: one per mood. */
export type Pose = Mood;

/** The figure family drawn for a placeholder, and its size on stage. */
export type FigureKind = "child" | "adult" | "gecko";

export type HairStyle = "puffs" | "braids" | "short" | "bun" | "wrap" | "bald";
export type BottomStyle = "skirt" | "dress" | "trousers" | "shorts";
export type Accessory = "glasses" | "tie" | "pointer" | "headband" | "coat" | "beard" | "basket";

/** What a placeholder figure looks like: enough to tell the cast apart. */
export interface Look {
  feminine: boolean;
  skin: string;
  hair: string;
  hairStyle: HairStyle;
  top: string;
  bottom: string;
  bottomStyle: BottomStyle;
  accent: string;
  accessories: Accessory[];
  /** Grey hair, for a grandparent or an elder. */
  elder?: boolean;
}

export interface StageActor {
  id: string;
  name: string;
  figure: FigureKind;
  isHero: boolean;
  isTutor: boolean;
  /** The teacher or supervisor: presents the concept cards. */
  isMentor: boolean;
  role?: CastRole;
  /** The key of this actor's pictures in `course.art.characters`. */
  artKey: string;
  look: Look;
  voice: { pitch: number; rate: number; profile: VoiceProfile };
}

/* -------------------------------------------------------------------------- */
/* Deterministic variety                                                      */
/* -------------------------------------------------------------------------- */

/** A small stable hash, so a cast member looks the same on every visit. */
export function hashOf(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function pick<T>(list: readonly T[], seed: number, salt = 0): T {
  return list[(seed + salt * 7919) % list.length];
}

/** West African skin tones, warm browns. */
const SKINS = ["#7a4a2c", "#5c3520", "#8d5a3b", "#4a2a18", "#9b6644"] as const;
const HAIRS = ["#1b1410", "#241812", "#2e1d14"] as const;
const TOPS = ["#e63946", "#2a9d8f", "#f4a261", "#457b9d", "#8e44ad", "#f1c40f", "#27ae60", "#e76f51", "#ffffff"] as const;
const BOTTOMS = ["#1d3557", "#5f6b7a", "#6d4c41", "#2b4ea2", "#3c4a3e"] as const;
const ACCENTS = ["#ffd23f", "#ff7eb6", "#06d6a0", "#ff9f1c", "#4cc9f0"] as const;

/**
 * Looks for the art keys of the older catalog, so stories written for it keep
 * their familiar faces: the teacher with glasses and a red tie, Papa Ben's
 * beard, Maman Olivia's head wrap, the girls' school uniform.
 */
const PRESETS: Record<string, Partial<Look>> = {
  nandi: {
    feminine: true, hairStyle: "puffs", top: "#ffffff", bottom: "#2b4ea2",
    bottomStyle: "skirt", accent: "#ffd23f", accessories: ["headband"],
  },
  friend: {
    feminine: true, hairStyle: "braids", top: "#ffffff", bottom: "#2b4ea2",
    bottomStyle: "skirt", accent: "#ff7eb6", accessories: ["headband"],
  },
  dodeine: { feminine: true, hairStyle: "puffs", top: "#f4a261", bottomStyle: "dress", bottom: "#f4a261" },
  tamobe: { feminine: true, hairStyle: "braids", top: "#06d6a0", bottomStyle: "dress", bottom: "#06d6a0" },
  papa_ben: {
    feminine: false, hairStyle: "short", top: "#e9c46a", bottom: "#3b2a20",
    bottomStyle: "trousers", accessories: ["beard"],
  },
  maman_olivia: {
    feminine: true, hairStyle: "wrap", top: "#2f6db5", bottom: "#2f6db5",
    bottomStyle: "dress", accent: "#8e44ad", accessories: ["basket"],
  },
  mr_kabore: {
    feminine: false, hairStyle: "short", top: "#cfe7fb", bottom: "#5f6b7a",
    bottomStyle: "trousers", accent: "#c1272d", accessories: ["glasses", "tie", "pointer"],
  },
  m_sanou: {
    feminine: false, hairStyle: "bald", top: "#2a9d8f", bottom: "#1d3557",
    bottomStyle: "trousers", accessories: ["glasses"],
  },
  tonton_issouf: {
    feminine: false, hairStyle: "short", top: "#f1faee", bottom: "#6d4c41",
    bottomStyle: "trousers", accessories: ["beard"],
  },
};

const FEMININE_WORDS: ReadonlySet<string> = new Set([
  "girl", "woman", "women", "lady", "female", "mother", "mum", "mom", "grandmother", "granny",
  "aunt", "sister", "daughter", "she", "her", "maman", "tantie", "madame", "fille", "femme",
]);
const MASCULINE_WORDS: ReadonlySet<string> = new Set([
  "boy", "man", "men", "male", "father", "dad", "grandfather", "grandpa", "uncle", "brother",
  "son", "he", "his", "him", "papa", "tonton", "monsieur", "garçon", "homme",
]);
/** A gendered word right after one of these is about someone else ("his daughter"). */
const POSSESSIVES: ReadonlySet<string> = new Set(["his", "her", "their", "its", "my", "your", "our", "a", "an"]);

/** A title in front of a name says who is meant: "M. Kaboré", "Mme Ouédraogo". */
const NAME_FEMININE = /^(mme|mrs|ms|miss|mlle|madame|maman|tantie)\.?\s/i;
const NAME_MASCULINE = /^(m|mr|monsieur|papa|tonton)\.?\s/i;

const COLOR_WORDS: Record<string, string> = {
  red: "#e63946", blue: "#2f6db5", navy: "#1d3557", green: "#2f9e5b", yellow: "#f1c40f",
  orange: "#f4a261", purple: "#8e44ad", pink: "#ff7eb6", white: "#f7f7f2", grey: "#8d99ae",
  gray: "#8d99ae", brown: "#6d4c41", black: "#2b2d42", teal: "#2a9d8f", turquoise: "#2ec4b6",
  gold: "#e9c46a", khaki: "#b5a26a", beige: "#e9d8b4", maroon: "#7b2d26",
};

/** The first colour named after `noun` (or before it) in a look sentence. */
function colorNear(look: string, nouns: RegExp): string | undefined {
  const words = look.toLowerCase().split(/[^a-z]+/);
  for (let i = 0; i < words.length; i += 1) {
    if (!nouns.test(words[i])) continue;
    for (let j = i - 1; j >= Math.max(0, i - 3); j -= 1) {
      const color = COLOR_WORDS[words[j]];
      if (color) return color;
    }
  }
  return undefined;
}

/**
 * What a look sentence says about the person's gender, if anything: the
 * earliest gendered word, skipping one that is about someone else ("holding
 * his daughter's hand", "a tie his sister gave him" → the person is "his").
 */
export function genderIn(sentence: string): boolean | undefined {
  if (!sentence) return undefined;
  const words = sentence.toLowerCase().split(/[^a-zà-ÿ'-]+/).map((word) => word.replace(/'s$/, ""));
  for (let i = 0; i < words.length; i += 1) {
    const word = words[i];
    const feminine = FEMININE_WORDS.has(word);
    const masculine = MASCULINE_WORDS.has(word);
    if (!feminine && !masculine) continue;
    // "her" and "his" stand for the person themselves; a noun after a
    // possessive ("his daughter") is someone else.
    const isPronoun = word === "her" || word === "his" || word === "him" || word === "he" || word === "she";
    if (!isPronoun && i > 0 && POSSESSIVES.has(words[i - 1]) && words[i - 1] !== "a" && words[i - 1] !== "an") {
      continue;
    }
    return feminine;
  }
  return undefined;
}

/** What a title in front of a name says, if anything. */
function genderOfName(name: string): boolean | undefined {
  if (NAME_FEMININE.test(name)) return true;
  if (NAME_MASCULINE.test(name)) return false;
  return undefined;
}

/**
 * A placeholder look from what the story says about someone: the hero
 * variant and the words of the `look` sentence first, then the old art key's
 * preset when it agrees with them, then a stable hash of the id for
 * everything still open.
 */
export function lookFor(member: CastMember, variant?: string): Look {
  const seed = hashOf(member.id || member.name || "?");
  // A hero variant describes itself; the member's own look is the default one.
  const lookText = (variant && member.variants?.find((v) => v?.id === variant)?.look) || member.look || "";
  const variantFeminine =
    variant && /^(girl|woman|f)/i.test(variant)
      ? true
      : variant && /^(boy|man|m)/i.test(variant)
        ? false
        : undefined;
  // What the story says beats what an art key was once drawn as: a preset
  // of the other gender is dropped whole (no beard, tie, headband or basket
  // carried over).
  const said = variantFeminine ?? genderIn(lookText);
  const rawPreset = PRESETS[member.art] ?? {};
  const preset =
    said !== undefined && rawPreset.feminine !== undefined && rawPreset.feminine !== said ? {} : rawPreset;

  const feminine = said ?? preset.feminine ?? genderOfName(member.name ?? "") ?? seed % 2 === 0;

  const look: Look = {
    feminine,
    skin: pick(SKINS, seed, 1),
    hair: pick(HAIRS, seed, 2),
    hairStyle: preset.hairStyle ?? (feminine ? pick(["puffs", "braids", "bun", "wrap"] as const, seed, 3) : pick(["short", "short", "bald"] as const, seed, 3)),
    top: preset.top ?? pick(TOPS, seed, 4),
    bottom: preset.bottom ?? pick(BOTTOMS, seed, 5),
    bottomStyle: preset.bottomStyle ?? (feminine ? pick(["skirt", "dress", "trousers"] as const, seed, 6) : pick(["trousers", "shorts"] as const, seed, 6)),
    accent: preset.accent ?? pick(ACCENTS, seed, 7),
    accessories: [...(preset.accessories ?? [])],
  };

  const words = lookText.toLowerCase();
  if (words) {
    if (/glasses|spectacles/.test(words)) look.accessories.push("glasses");
    if (/\btie\b/.test(words)) look.accessories.push("tie");
    if (/beard|moustache|mustache/.test(words) && !look.feminine) look.accessories.push("beard");
    if (/white coat|lab coat|doctor'?s coat/.test(words)) look.accessories.push("coat");
    if (/head ?wrap|headscarf|head scarf|turban|hijab|gele/.test(words)) look.hairStyle = "wrap";
    else if (/braid|cornrow|locs|dreadlock/.test(words)) look.hairStyle = "braids";
    else if (/puff|afro/.test(words)) look.hairStyle = "puffs";
    else if (/\bbun\b/.test(words)) look.hairStyle = "bun";
    else if (/bald|shaved/.test(words)) look.hairStyle = "bald";
    else if (/short hair|cropped/.test(words)) look.hairStyle = "short";
    if (/headband|hair ?band|ribbon/.test(words)) look.accessories.push("headband");
    if (/basket/.test(words)) look.accessories.push("basket");
    // A head wrap or a tie is drawn in the accent colour: take the one the look names.
    const accent = colorNear(words, /^(wrap|headwrap|headscarf|scarf|turban|gele|tie|necktie)$/);
    if (accent) look.accent = accent;
    if (/\bdress\b|boubou|pagne/.test(words)) look.bottomStyle = "dress";
    else if (/skirt/.test(words)) look.bottomStyle = "skirt";
    else if (/shorts/.test(words)) look.bottomStyle = "shorts";
    else if (/trousers|pants|jeans/.test(words)) look.bottomStyle = "trousers";
    if (/grey hair|gray hair|white hair|elderly|grandmother|grandfather|old man|old woman/.test(words)) look.elder = true;
    if (/light skin|light-brown|light brown|fair/.test(words)) look.skin = "#b07a52";
    else if (/very dark|deep brown|dark skin|dark-brown|dark brown/.test(words)) look.skin = "#4a2a18";
    else if (/medium brown|brown skin/.test(words)) look.skin = "#7a4a2c";
    const top = colorNear(words, /^(shirt|blouse|top|t|tee|tshirt|jacket|sweater|polo|tunic|uniform|coat|boubou)$/);
    if (top) look.top = top;
    const bottom = colorNear(words, /^(skirt|trousers|pants|shorts|jeans|dress|wrapper|pagne)$/);
    if (bottom) look.bottom = bottom;
    if (look.bottomStyle === "dress" && !bottom) look.bottom = look.top;
  }
  return look;
}

/* -------------------------------------------------------------------------- */
/* The cast                                                                   */
/* -------------------------------------------------------------------------- */

/** The learner's own character: by role, by id, or the learner's name. */
export function isHero(member: CastMember, course: Pick<StoryCourse, "learner">): boolean {
  if (member.role === "hero" || member.id === "hero") return true;
  const first = course.learner?.first_name?.trim();
  return !!first && !first.includes("{") && member.name?.trim() === first;
}

export function isTutor(member: CastMember): boolean {
  return member.kind === "ai_tutor" || member.role === "tutor" || member.id === "margo";
}

/** The hero's variants, when there is a real choice to offer (#2672). */
export function heroVariants(course: Pick<StoryCourse, "cast" | "learner">): string[] {
  const hero = (course.cast ?? []).find((member) => isHero(member, course));
  const ids = (hero?.variants ?? []).map((variant) => variant?.id).filter(Boolean) as string[];
  return ids.length >= 2 ? ids : [];
}

const DEFAULT_VOICES: Record<FigureKind, { pitch: number; rate: number }> = {
  child: { pitch: 1.35, rate: 1 },
  adult: { pitch: 0.95, rate: 0.95 },
  gecko: { pitch: 1.6, rate: 1.05 },
};

function figureOf(member: CastMember, variant?: string): FigureKind {
  if (isTutor(member) || member.kind === "animal") return "gecko";
  if (variant && /^(woman|man)$/i.test(variant)) return "adult";
  if (variant && /^(girl|boy)$/i.test(variant)) return "child";
  return member.kind === "child" ? "child" : "adult";
}

function clampVoice(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}

/** Which AI voice speaks for a cast member (#2704): Margo, a child or an adult. */
export function voiceProfileOf(figure: FigureKind, look: Pick<Look, "feminine">, tutor: boolean): VoiceProfile {
  if (tutor || figure === "gecko") return "tutor";
  if (figure === "child") return look.feminine ? "girl" : "boy";
  return look.feminine ? "woman" : "man";
}

/** Every cast member, ready for the stage. `variant` is the hero's chosen look. */
export function buildActors(
  course: Pick<StoryCourse, "cast" | "learner">,
  variant: string | undefined,
): Map<string, StageActor> {
  const actors = new Map<string, StageActor>();
  for (const member of course.cast ?? []) {
    if (!member?.id) continue;
    const hero = isHero(member, course);
    const heroVariant = hero && member.variants?.some((v) => v?.id === variant) ? variant : undefined;
    const figure = figureOf(member, heroVariant);
    const defaults = DEFAULT_VOICES[figure];
    const look = lookFor(member, heroVariant);
    actors.set(member.id, {
      id: member.id,
      name: member.name || member.id,
      figure,
      isHero: hero,
      isTutor: isTutor(member),
      isMentor: member.role === "mentor" || member.id === "mentor",
      role: member.role,
      artKey: heroVariant ? `hero:${heroVariant}` : member.id,
      look,
      voice: {
        pitch: clampVoice(member.voice?.pitch, defaults.pitch, 0, 2),
        rate: clampVoice(member.voice?.rate, defaults.rate, 0.5, 2),
        profile: voiceProfileOf(figure, look, isTutor(member)),
      },
    });
  }
  distinctOutfits([...actors.values()]);
  return actors;
}

/* -------------------------------------------------------------------------- */
/* Everyone dressed differently                                               */
/* -------------------------------------------------------------------------- */

/** Clearly different top colours, tried in a per-person order. */
const OUTFIT_TOPS = [
  "#e63946", "#2a9d8f", "#f4a261", "#457b9d", "#8e44ad", "#f1c40f",
  "#27ae60", "#ff7eb6", "#4cc9f0", "#ffffff", "#7b2d26", "#06d6a0",
] as const;
const OUTFIT_BOTTOMS = ["#1d3557", "#6d4c41", "#3c4a3e", "#5f6b7a", "#2b4ea2", "#7b2d26"] as const;

function rgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "").padEnd(6, "0");
  return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) || 0) as [number, number, number];
}

/** Two colours a child would call the same. */
function alike(a: string, b: string): boolean {
  const [r1, g1, b1] = rgb(a);
  const [r2, g2, b2] = rgb(b);
  return Math.hypot(r1 - r2, g1 - g2, b1 - b2) < 90;
}

const ROLE_ORDER: Record<string, number> = { hero: 0, friend: 1, mentor: 2, family: 3 };

/**
 * No two people on the cast wear the same outfit: the hero keeps theirs,
 * and everyone after (the friend first) takes the next colour, in an order
 * fixed by their id, that nobody before has. The hero and the friend also
 * never share a cut (dress, skirt, trousers, shorts) or a hair accent.
 */
export function distinctOutfits(actors: StageActor[]): void {
  const people = actors
    .filter((actor) => actor.figure !== "gecko")
    .sort((a, b) => {
      const rank = (actor: StageActor) =>
        actor.isHero ? -1 : ROLE_ORDER[actor.role ?? actor.id] ?? 4;
      return rank(a) - rank(b) || a.id.localeCompare(b.id);
    });
  const tops: string[] = [];
  const bottoms: string[] = [];
  const accents: string[] = [];
  const hero = people.find((actor) => actor.isHero);
  for (const actor of people) {
    const look = actor.look;
    const seed = hashOf(actor.id);
    const wasDress = look.bottomStyle === "dress";
    if (tops.some((taken) => alike(taken, look.top))) {
      const free = OUTFIT_TOPS.map((_, i) => OUTFIT_TOPS[(seed + i) % OUTFIT_TOPS.length]).find(
        (candidate) => !tops.some((taken) => alike(taken, candidate)),
      );
      if (free) look.top = free;
    }
    if (wasDress) look.bottom = look.top;
    else if (bottoms.some((taken) => alike(taken, look.bottom))) {
      const free = OUTFIT_BOTTOMS.map((_, i) => OUTFIT_BOTTOMS[(seed + i) % OUTFIT_BOTTOMS.length]).find(
        (candidate) => !bottoms.some((taken) => alike(taken, candidate)) && !alike(candidate, look.top),
      );
      if (free) look.bottom = free;
    }
    if (accents.some((taken) => alike(taken, look.accent))) {
      const free = ["#ffd23f", "#ff7eb6", "#06d6a0", "#ff9f1c", "#4cc9f0", "#c77dff"].find(
        (candidate) => !accents.some((taken) => alike(taken, candidate)),
      );
      if (free) look.accent = free;
    }
    // The hero's best friend never comes in the hero's cut either.
    const isFriend = actor.role === "friend" || actor.id === "friend" || actor.id === "peer";
    if (hero && actor !== hero && isFriend && look.bottomStyle === hero.look.bottomStyle) {
      const other: Record<BottomStyle, BottomStyle> = look.feminine
        ? { dress: "skirt", skirt: "dress", trousers: "skirt", shorts: "skirt" }
        : { trousers: "shorts", shorts: "trousers", dress: "trousers", skirt: "trousers" };
      look.bottomStyle = other[look.bottomStyle];
      if (look.bottomStyle === "dress") look.bottom = look.top;
    }
    tops.push(look.top);
    if (look.bottomStyle !== "dress") bottoms.push(look.bottom);
    accents.push(look.accent);
  }
}

/* -------------------------------------------------------------------------- */
/* Pictures                                                                    */
/* -------------------------------------------------------------------------- */

const KNOWN_POSES: ReadonlySet<string> = new Set([
  "idle", "talk", "happy", "think", "sad", "surprised", "walk",
]);

/** The pose for a mood; an unknown mood reads as talking. */
export function poseFor(mood: string | undefined, speaking: boolean): Pose {
  if (mood && KNOWN_POSES.has(mood)) return mood as Pose;
  return speaking ? "talk" : "idle";
}

/**
 * The art pipeline draws idle, talk, happy and think. Every other pose falls
 * back to the nearest of those, and anything missing to idle.
 */
const ART_LADDER: Record<Pose, readonly string[]> = {
  idle: ["idle"],
  talk: ["talk", "idle"],
  happy: ["happy", "talk", "idle"],
  think: ["think", "idle"],
  sad: ["sad", "think", "idle"],
  surprised: ["surprised", "happy", "talk", "idle"],
  walk: ["walk", "idle"],
};

/** Only URLs the player can safely put in an `<img src>`. */
export function safeArtUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const url = value.trim();
  if (!url) return undefined;
  if (url.startsWith("/") && !url.startsWith("//")) return url;
  if (/^https:\/\//i.test(url)) return url;
  if (/^data:image\/(png|webp|jpeg|gif|svg\+xml);/i.test(url)) return url;
  return undefined;
}

/** The generated picture for an actor in a pose, or undefined for a placeholder. */
export function artFor(art: StoryArt | undefined, key: string, pose: Pose): string | undefined {
  const poses = art?.characters?.[key];
  if (!poses) return undefined;
  for (const candidate of ART_LADDER[pose] ?? ["idle"]) {
    const url = safeArtUrl(poses[candidate]);
    if (url) return url;
  }
  return undefined;
}

/* -------------------------------------------------------------------------- */
/* Layout                                                                     */
/* -------------------------------------------------------------------------- */

/** Where each of `count` actors stands, as a % of the stage width. */
export function slotsFor(count: number): number[] {
  switch (count) {
    case 0:
      return [];
    case 1:
      return [18];
    case 2:
      return [17, 83];
    case 3:
      return [15, 50, 85];
    default: {
      const step = 76 / (count - 1);
      return Array.from({ length: count }, (_, i) => 12 + i * step);
    }
  }
}

/** Figure height as a share of the stage height. */
export const FIGURE_HEIGHT: Record<FigureKind, number> = {
  adult: 50,
  child: 42,
  gecko: 22,
};

/** The ground line, as a share of the stage height from the bottom. */
export const GROUND = 7;

/**
 * The order actors stand in: the hero on the left (where the question cards
 * leave room to react), the tutor gecko on the far right, the rest between.
 */
export function stageOrder(ids: string[], actors: Map<string, StageActor>): string[] {
  const known = ids.filter((id, index) => actors.has(id) && ids.indexOf(id) === index);
  const rank = (id: string) => {
    const actor = actors.get(id);
    if (actor?.isHero) return 0;
    if (actor?.isTutor) return 2;
    return 1;
  };
  return [...known].sort((a, b) => rank(a) - rank(b));
}
