/**
 * The story as a list of beats for the stage: one entry per step, with the
 * chapter and scene it belongs to and who stands on stage while it plays.
 *
 * Who is on stage: the scene's own `cast` (#2672) plus whoever speaks in it.
 * A scene of older stories often has no speaker at all (a concept card and
 * its question): the people of the scene before stay on, or the chapter's
 * speakers, or the course's teacher, so the stage is never left empty.
 */

import type { Chapter, Prop, PropMedia, Step, TextObject } from "@/lib/story-course/types";

import { stageOrder, type StageActor } from "./cast";
import { closeUpProp, pictureFor, planSceneProps, sameOriginMedia } from "./props";

/** What the planner needs to know about the story's props (#2681). */
export interface PropContext {
  props: ReadonlyMap<string, Prop>;
  media?: Readonly<Record<string, PropMedia>>;
}

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
  /** Prop ids on stage at this step (#2681). */
  props: string[];
  /** Props popping in at this step. */
  entering: string[];
  /** Props this step's line names: they bounce. */
  pointed: string[];
  /** Every prop the scene uses, for fetching their pictures ahead. */
  sceneProps: string[];
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

/**
 * A close-up of a prop with nothing to show (no picture, no sticker) is
 * dropped: the line before it already names the thing, and an empty card is
 * worse than none. Progress is kept per unit, not per step, so this is safe.
 */
function keepsStep(step: Step, context: PropContext | undefined): boolean {
  const id = closeUpProp(step);
  if (!id) return true;
  const prop = context?.props.get(id);
  if (!prop) return false;
  const media = context?.media?.[id];
  return !!pictureFor(prop, media, "en") || !!sameOriginMedia(media?.sticker);
}

export function planSteps(
  chapters: Chapter[],
  allChapters: Chapter[],
  actors: Map<string, StageActor>,
  context?: PropContext,
): PlannedStep[] {
  const out: PlannedStep[] = [];
  const known = context?.props ?? new Map<string, Prop>();
  for (const chapter of chapters) {
    const chapterNumber = Math.max(1, allChapters.findIndex((c) => c.id === chapter.id) + 1);
    const chapterSpeakers = speakersOf((chapter.scenes ?? []).flatMap((scene) => scene.steps ?? [])).filter(
      (id) => actors.has(id),
    );
    let carried: string[] = [];
    let carriedProps: string[] = [];
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
      const newPlace = scene.place !== lastPlace;
      if (newPlace) placeRun = out.length;
      lastPlace = scene.place;
      const steps = (scene.steps ?? []).filter((step) => keepsStep(step, context));
      // Props carry over within a stretch at one place; a new place starts afresh.
      const propPlan = planSceneProps(scene.props, steps, known, newPlace ? [] : carriedProps);
      const sceneProps = unique([
        ...(scene.props ?? []).filter((id) => known.has(id)),
        ...propPlan.flatMap((entry) => entry.props),
      ]);
      let firstOfScene = true;
      steps.forEach((step, index) => {
        const props = propPlan[index] ?? { props: [], entering: [], pointed: [] };
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
          props: props.props,
          entering: props.entering,
          pointed: props.pointed,
          sceneProps,
        });
        firstOfChapter = false;
        firstOfScene = false;
      });
      carriedProps = propPlan.length ? propPlan[propPlan.length - 1].props : carriedProps;
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
