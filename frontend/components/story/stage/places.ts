/**
 * Where a scene happens, and how its placeholder backdrop is drawn.
 *
 * A course's own places (#2672) come with a generated backdrop; until it
 * exists, and for stories that only name a key of the older catalog, the
 * stage paints a placeholder in the Scratch prototype's style. The theme is
 * read from the place id and its English `look`, so an adult course's
 * "clinic" or "district_office" gets a fitting set rather than a classroom.
 */

import type { StoryCourse, TextObject } from "@/lib/story-course/types";

import { hashOf } from "./cast";

export type PlaceTheme =
  | "classroom"
  | "market"
  | "farm"
  | "home"
  | "kitchen"
  | "yard"
  | "road"
  | "shop"
  | "desk"
  | "city"
  | "clinic"
  | "office"
  | "lab"
  | "village"
  | "savanna";

/** The older catalog's places (backend `PLACES`). */
const CATALOG: Record<string, PlaceTheme> = {
  home: "home",
  kitchen: "kitchen",
  market: "market",
  classroom: "classroom",
  school_yard: "yard",
  mango_farm: "farm",
  bus_station: "road",
  shop: "shop",
  desk: "desk",
  montreal: "city",
};

/** Titles for the catalog places, which carry none of their own. */
const CATALOG_TITLES: Record<string, TextObject> = {
  home: { en: "At home", fr: "À la maison" },
  kitchen: { en: "In the kitchen", fr: "Dans la cuisine" },
  market: { en: "At the market", fr: "Au marché" },
  classroom: { en: "In class", fr: "En classe" },
  school_yard: { en: "In the schoolyard", fr: "Dans la cour" },
  mango_farm: { en: "At the mango farm", fr: "Au verger de mangues" },
  bus_station: { en: "At the bus station", fr: "À la gare routière" },
  shop: { en: "At the shop", fr: "À la boutique" },
  desk: { en: "At my desk", fr: "À mon bureau" },
  montreal: { en: "In Montréal", fr: "À Montréal" },
};

const KEYWORDS: ReadonlyArray<[RegExp, PlaceTheme]> = [
  [/class ?room|lecture|tutorial room|salle de classe|chalkboard|blackboard/, "classroom"],
  [/clinic|hospital|health|sant[eé]|dispensar|maternit|pharmac|\bward\b|surgery|cs[ps]s?\b/, "clinic"],
  [/\blab|laborator/, "lab"],
  [/office|bureau|meeting|workplace|ministry|headquarter|council|desk/, "office"],
  [/market|march[eé]|stall/, "market"],
  [/shop|store|boutique|kiosk|pharmacy counter/, "shop"],
  [/kitchen|cuisine/, "kitchen"],
  [/farm|field|garden|orchard|verger|champ|plantation|crop/, "farm"],
  [/school ?yard|playground|cour d|school/, "yard"],
  [/road|bus|station|street|gare|route|taxi|truck/, "road"],
  [/city|town|ville|downtown|skyline/, "city"],
  [/home|house|maison|compound|living room|bedroom/, "home"],
  [/village|well|puits|pond|river|mare|borehole|water point/, "village"],
  [/savann|bush|baobab|desert|sahel/, "savanna"],
];

/** Indoor sets get a wall and a floor instead of a sky and the ground. */
export const INDOOR: ReadonlySet<PlaceTheme> = new Set([
  "classroom",
  "kitchen",
  "desk",
  "office",
  "lab",
]);

export function placeTheme(placeId: string, look?: string): PlaceTheme {
  const id = (placeId || "").toLowerCase();
  if (CATALOG[id]) return CATALOG[id];
  const words = `${id.replace(/[_-]+/g, " ")} ${(look ?? "").toLowerCase()}`;
  for (const [pattern, theme] of KEYWORDS) {
    if (pattern.test(id.replace(/[_-]+/g, " "))) return theme;
  }
  for (const [pattern, theme] of KEYWORDS) {
    if (pattern.test(words)) return theme;
  }
  return hashOf(id) % 2 === 0 ? "savanna" : "village";
}

export type SkyMood = "dawn" | "day" | "evening";

/** Outdoor places differ in the time of day, so two of them never look alike. */
export function skyFor(placeId: string): SkyMood {
  return (["dawn", "day", "day", "evening"] as const)[hashOf(placeId || "?") % 4];
}

/** A scene's place title: the course's own, else the catalog's. */
export function placeTitle(
  course: Pick<StoryCourse, "places">,
  placeId: string,
): TextObject | undefined {
  const own = (course.places ?? []).find((place) => place?.id === placeId);
  if (own?.title && Object.keys(own.title).length) return own.title;
  return CATALOG_TITLES[placeId];
}

export function placeLook(course: Pick<StoryCourse, "places">, placeId: string): string | undefined {
  return (course.places ?? []).find((place) => place?.id === placeId)?.look;
}
