/**
 * The story as a list of beats for the stage: one entry per step, with the
 * chapter and scene it belongs to and who stands on stage while it plays.
 *
 * Who is on stage: the scene's own `cast` (#2672) plus whoever speaks in it.
 * A scene of older stories often has no speaker at all (a concept card and
 * its question): the people of the scene before stay on, or the chapter's
 * speakers, or the course's teacher, so the stage is never left empty.
 */

import type { Chapter, Step, TextObject } from "@/lib/story-course/types";

import { stageOrder, type StageActor } from "./cast";

export interface PlannedStep {
  step: Step;
  chapterId: string;
  /** 1-based position of the chapter in the whole story. */
  chapterNumber: number;
  chapterTitle: TextObject;
  sceneId: string;
  place: string;
  /** First step of its chapter: its title card shows. */
  startsChapter: boolean;
  /** First step of its scene. */
  startsScene: boolean;
  /**
   * The index of the step that opened this stretch at the same place (a new
   * chapter opens a new one). The stage keys the scene on it: a new place
   * irises in and the cast walks on again; the same place carries on.
   */
  placeRun: number;
  /** Cast ids on stage, left to right. */
  cast: string[];
}

/** At most this many on stage: beyond, a 320px stage gets crowded. */
const MAX_ON_STAGE = 4;

function unique(ids: string[]): string[] {
  return ids.filter((id, index) => ids.indexOf(id) === index);
}

function speakersOf(steps: Step[] | undefined): string[] {
  return unique((steps ?? []).filter((step) => step.type === "say" && step.who).map((step) => String(step.who)));
}

/** The teacher, or failing that the first grown-up, for a scene nobody speaks in. */
function defaultCast(actors: Map<string, StageActor>): string[] {
  const list = [...actors.values()];
  const mentor =
    list.find((actor) => actor.isMentor) ??
    list.find((actor) => !actor.isHero && !actor.isTutor && actor.figure === "adult") ??
    list.find((actor) => !actor.isTutor);
  const hero = list.find((actor) => actor.isHero);
  return unique([hero?.id, mentor?.id].filter(Boolean) as string[]);
}

export function planSteps(
  chapters: Chapter[],
  allChapters: Chapter[],
  actors: Map<string, StageActor>,
): PlannedStep[] {
  const out: PlannedStep[] = [];
  for (const chapter of chapters) {
    const chapterNumber = Math.max(1, allChapters.findIndex((c) => c.id === chapter.id) + 1);
    const chapterSpeakers = speakersOf((chapter.scenes ?? []).flatMap((scene) => scene.steps ?? [])).filter(
      (id) => actors.has(id),
    );
    let carried: string[] = [];
    let firstOfChapter = true;
    let lastPlace: string | null = null;
    let placeRun = out.length;
    for (const scene of chapter.scenes ?? []) {
      const declared = (scene.cast ?? []).filter((id) => actors.has(id));
      const speakers = speakersOf(scene.steps).filter((id) => actors.has(id));
      let ids = unique([...declared, ...speakers]);
      if (!ids.length) {
        ids = carried.length
          ? carried
          : chapterSpeakers.length
            ? chapterSpeakers.slice(0, 2)
            : defaultCast(actors);
      }
      carried = ids;
      const cast = stageOrder(ids, actors).slice(0, MAX_ON_STAGE);
      if (scene.place !== lastPlace) placeRun = out.length;
      lastPlace = scene.place;
      let firstOfScene = true;
      for (const step of scene.steps ?? []) {
        out.push({
          step,
          chapterId: chapter.id,
          chapterNumber,
          chapterTitle: chapter.title,
          sceneId: scene.id,
          place: scene.place,
          startsChapter: firstOfChapter,
          startsScene: firstOfScene,
          placeRun,
          cast,
        });
        firstOfChapter = false;
        firstOfScene = false;
      }
    }
  }
  return out;
}

/** The one who reacts to an answer: the hero when on stage, else the first one there. */
export function reactorOf(cast: string[], actors: Map<string, StageActor>): string | undefined {
  return cast.find((id) => actors.get(id)?.isHero) ?? cast[0];
}

/** The one who presents a concept card: the teacher when on stage. */
export function presenterOf(cast: string[], actors: Map<string, StageActor>): string | undefined {
  return (
    cast.find((id) => actors.get(id)?.isMentor) ??
    cast.find((id) => {
      const actor = actors.get(id);
      return actor && !actor.isHero && !actor.isTutor && actor.figure === "adult";
    }) ??
    cast.find((id) => !actors.get(id)?.isHero) ??
    cast[0]
  );
}
