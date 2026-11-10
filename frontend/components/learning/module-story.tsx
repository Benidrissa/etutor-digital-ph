'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ScrollText,
  WifiOff,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { choicesKeyFor, readChoices } from '@/components/story/stage/prefs';
import { StoryPlayer, type PlayerSnapshot } from '@/components/story/story-player';
import { SubscriptionRequired } from '@/components/shared/subscription-required';
import { Link } from '@/i18n/routing';
import { ApiError, apiFetch, getModuleDetailWithProgress, type UnitProgressDetail } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { completeLessonUnit } from '@/lib/learning/complete-lesson';
import { OfflineContentNotAvailable } from '@/lib/offline/content-loader';
import { starsFor, text } from '@/lib/story-course/answer';
import {
  isStoryDocument,
  isStoryGenerating,
  isStoryUnavailableError,
  storyErrorCode,
} from '@/lib/story-course/api';
import { isNetworkFailure, loadModuleStory } from '@/lib/story-course/load';
import { firstNameOf, personalizeStory } from '@/lib/story-course/personalize';
import {
  chapterKey,
  completedChapterCount,
  firstIncompleteChapter,
  readStoryProgress,
  withChapterDone,
  withChapterSnapshot,
  writeStoryProgress,
  type StoryProgress,
} from '@/lib/story-course/progress';
import type { Chapter, ChapterCovers, StoryCourse } from '@/lib/story-course/types';

import { ModuleStorySkeleton } from './module-story-skeleton';

/**
 * Polling a module story being written. The first open writes every chapter
 * (and any lesson or quiz not generated yet), which takes minutes, not
 * seconds: poll gently, tell the learner after 30 s that they can leave, and
 * stop after 30 min (story generator v4, #2680, can take longer than 15) —
 * the task keeps running, and the next open joins it.
 */
export const POLL_INTERVAL_MS = 5000;
export const POLL_TIMEOUT_MS = 30 * 60 * 1000;
export const LEAVE_HINT_MS = 30 * 1000;
/**
 * Status polls in a row that may fail on the way (the request dropped, a
 * 429 or a 5xx) before the panel gives up: about 2 min of a lost link.
 */
export const POLL_MAX_CONSECUTIVE_ERRORS = 24;

type PanelState =
  | { kind: 'loading' }
  | { kind: 'generating'; slow: boolean }
  | { kind: 'ready'; story: StoryCourse }
  /** 409 story_unavailable, no_story_content, or any other 403/404. */
  | { kind: 'unavailable' }
  /** detail.error story_mode_disabled: story mode is switched off. */
  | { kind: 'disabled' }
  /** 403 subscription_required: the module has paid units. */
  | { kind: 'subscription' }
  | { kind: 'offline' }
  | { kind: 'failed'; reason: 'failed' | 'timeout' };

interface ContentStatus {
  status: string;
  content_id?: string;
  error?: string;
}

type UnitKind = 'lesson' | 'quiz' | 'case';

/** How the chapter list names a chapter: the rally has its own name. */
function chapterKind(covers: ChapterCovers | undefined): UnitKind | 'rally' {
  return covers?.rally ? 'rally' : unitKind(covers);
}

/**
 * The kind of unit a chapter stands for. The rally (#2674) is played in the
 * story but stands for the module's quiz unit, which it does not complete:
 * its link sends the learner to the quiz.
 */
function unitKind(covers: ChapterCovers | undefined): UnitKind {
  if (covers?.role === 'quiz_checkpoint') return 'quiz';
  if (covers?.role === 'case_checkpoint') return 'case';
  return 'lesson';
}

/** A chapter that points the learner to its unit's own page. */
function sendsToUnit(covers: ChapterCovers | undefined): covers is ChapterCovers {
  return !!covers && (covers.role !== 'lesson' || covers.status === 'unavailable');
}

function isOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

/** A status poll that failed on the way, not an answer about the task. */
function isTransientPollError(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 429 || err.status >= 500;
  return isNetworkFailure(err);
}

function fromError(err: unknown): PanelState {
  if (err instanceof OfflineContentNotAvailable) return { kind: 'offline' };
  if (err instanceof ApiError && err.code === 'subscription_required') {
    return { kind: 'subscription' };
  }
  // The body's code decides first, whatever the status: switched off is a
  // 404 `story_mode_disabled`, not a 403.
  switch (storyErrorCode(err)) {
    case 'story_mode_disabled':
      return { kind: 'disabled' };
    case 'story_unavailable':
    case 'no_story_content':
    case 'module_not_found':
    case 'story_not_cached':
      return { kind: 'unavailable' };
  }
  if (isStoryUnavailableError(err)) return { kind: 'unavailable' };
  if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
    return { kind: 'unavailable' };
  }
  return { kind: 'failed', reason: 'failed' };
}

interface ModuleStoryProps {
  moduleId: string;
  /** The interface language: the story is generated and cached per language. */
  language: 'fr' | 'en';
}

/**
 * The module story page's panel: the whole module retold as one story, one
 * chapter per unit, in which the learner is the hero.
 *
 * GET /api/v1/story-courses/module/{id} answers 200 with the story, 202 while
 * it is written (polled on the shared /content/status endpoint), 409 when no
 * valid story could be assembled, or 403 subscription_required. Reads go
 * through loadModuleStory, so a downloaded module's story opens offline.
 */
export function ModuleStory({ moduleId, language }: ModuleStoryProps) {
  const t = useTranslations('ModuleStory');
  const { user, isHydrated } = useCurrentUser();
  const [state, setState] = useState<PanelState>({ kind: 'loading' });
  // Bumped by Retry to re-run the fetch; a counter only moves on a click.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Wait for the localStorage-backed user: the story needs the learner's
    // name, and fetching before hydration is how viewers once dispatched
    // duplicate generation tasks.
    if (!isHydrated) return;

    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let hintTimer: ReturnType<typeof setTimeout> | null = null;

    function settle(next: PanelState) {
      if (cancelled) return;
      if (hintTimer) {
        clearTimeout(hintTimer);
        hintTimer = null;
      }
      setState(next);
    }

    function startGenerating(taskId: string, startedAt: number) {
      if (cancelled) return;
      setState((prev) => (prev.kind === 'generating' ? prev : { kind: 'generating', slow: false }));
      if (!hintTimer) {
        const wait = Math.max(0, LEAVE_HINT_MS - (Date.now() - startedAt));
        hintTimer = setTimeout(() => {
          if (cancelled) return;
          setState((prev) => (prev.kind === 'generating' ? { kind: 'generating', slow: true } : prev));
        }, wait);
      }
      poll(taskId, startedAt);
    }

    /** Show the story, or keep polling while it is still being written. */
    function accept(data: unknown, startedAt: number) {
      if (isStoryGenerating(data)) {
        // Without a task id we would poll /content/status/undefined forever.
        if (!data.task_id) {
          settle({ kind: 'failed', reason: 'failed' });
          return;
        }
        startGenerating(data.task_id, startedAt);
        return;
      }
      if (!isStoryDocument(data) || data.chapters.length === 0) {
        settle(isStoryDocument(data) ? { kind: 'unavailable' } : { kind: 'failed', reason: 'failed' });
        return;
      }
      settle({ kind: 'ready', story: data });
    }

    /** `errors`: transient status failures in a row, so far. */
    function poll(taskId: string, startedAt: number, errors = 0) {
      pollTimer = setTimeout(async () => {
        if (cancelled) return;
        if (Date.now() - startedAt >= POLL_TIMEOUT_MS) {
          settle({ kind: 'failed', reason: 'timeout' });
          return;
        }
        let status: ContentStatus;
        try {
          status = await apiFetch<ContentStatus>(`/api/v1/content/status/${taskId}`);
        } catch (err) {
          if (cancelled) return;
          // A dropped request or a 5xx (a flaky 2G link, a deploy) says
          // nothing about the task, which keeps writing: ask again on the
          // next tick, under the same 30 min cap.
          if (isTransientPollError(err) && errors + 1 < POLL_MAX_CONSECUTIVE_ERRORS) {
            poll(taskId, startedAt, errors + 1);
          } else {
            settle(fromError(err));
          }
          return;
        }
        if (cancelled) return;
        try {
          if (status.status === 'complete') {
            // Re-read through the loader, so the finished story is also
            // stored for offline use.
            const data = await loadModuleStory(moduleId, language);
            if (cancelled) return;
            accept(data, startedAt);
          } else if (status.status === 'failed') {
            settle(
              status.error?.includes('story_unavailable')
                ? { kind: 'unavailable' }
                : { kind: 'failed', reason: 'failed' },
            );
          } else {
            poll(taskId, startedAt);
          }
        } catch (err) {
          settle(fromError(err));
        }
      }, POLL_INTERVAL_MS);
    }

    async function run() {
      try {
        const data = await loadModuleStory(moduleId, language);
        if (cancelled) return;
        accept(data, Date.now());
      } catch (err) {
        settle(fromError(err));
      }
    }

    void run();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (hintTimer) clearTimeout(hintTimer);
    };
    // `state` is deliberately not a dependency: a status flip would restart
    // the fetch and kill the poll timer.
  }, [isHydrated, moduleId, language, attempt]);

  // One cached story serves every learner: their first name goes in at
  // display time, on a copy, so the cached document stays name-free. The
  // friend's name is the learner's own choice, asked by the player itself.
  const firstName = firstNameOf(user?.name);
  const story = state.kind === 'ready' ? state.story : null;
  const personalized = useMemo(
    () =>
      story
        ? personalizeStory(story, { child: firstName, language, keep: ['friend'] })
        : null,
    [story, firstName, language],
  );

  const retry = () => {
    setState({ kind: 'loading' });
    setAttempt((n) => n + 1);
  };

  if (story && personalized) {
    return (
      <ModuleStoryReader
        // A new revision is a new story, and another learner has their own
        // progress: either way it is read afresh.
        key={`${story.id}:${story.module_story?.revision ?? ''}:${user?.id ?? ''}`}
        storyId={story.id}
        userId={user?.id ?? null}
        story={personalized}
        moduleId={moduleId}
        language={language}
      />
    );
  }

  if (state.kind === 'loading' || state.kind === 'ready') {
    return <ModuleStorySkeleton />;
  }

  if (state.kind === 'subscription') {
    return (
      <SubscriptionRequired
        secondaryAction={
          <Link
            href={`/modules/${moduleId}`}
            className="inline-flex min-h-11 items-center text-sm text-stone-600 hover:text-stone-900"
          >
            {t('backToModule')}
          </Link>
        }
      />
    );
  }

  const heading = (
    <h1 className="mb-2 text-xl font-bold text-gray-900">{t('pageTitle')}</h1>
  );

  if (state.kind === 'generating') {
    return (
      <div className="mx-auto max-w-2xl">
        {heading}
        <div className="flex flex-col items-center py-10 text-center" role="status">
          <Loader2 className="mb-4 h-8 w-8 animate-spin text-teal-600" aria-hidden="true" />
          <p className="font-semibold text-gray-900">{t('generating')}</p>
          <p className="mt-1 max-w-md text-sm text-gray-600">{t('generatingDescription')}</p>
          {state.slow ? (
            <p className="mt-4 max-w-sm text-sm text-amber-800">{t('leaveHint')}</p>
          ) : null}
        </div>
      </div>
    );
  }

  if (state.kind === 'unavailable' || state.kind === 'disabled') {
    return (
      <div className="mx-auto max-w-2xl">
        {heading}
        <div className="flex flex-col items-center py-10 text-center">
          <ScrollText className="mb-3 h-8 w-8 text-stone-400" aria-hidden="true" />
          <p className="font-medium text-gray-900">
            {state.kind === 'unavailable' ? t('unavailable') : t('disabled')}
          </p>
          <p className="mt-1 max-w-md text-sm text-gray-600">{t('unavailableHint')}</p>
        </div>
      </div>
    );
  }

  const offline = state.kind === 'offline';
  const message = offline
    ? t('offline')
    : state.reason === 'timeout'
      ? t('timeout')
      : t('failed');
  return (
    <div className="mx-auto max-w-2xl">
      {heading}
      <div className="flex flex-col items-center py-10 text-center">
        {offline ? (
          <WifiOff className="mb-3 h-8 w-8 text-stone-400" aria-hidden="true" />
        ) : (
          <AlertTriangle className="mb-3 h-8 w-8 text-red-500" aria-hidden="true" />
        )}
        <p className="max-w-md text-gray-700" role="alert">
          {message}
        </p>
        <Button variant="outline" onClick={retry} className="mt-4 min-h-11">
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          {t('retry')}
        </Button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

interface ReaderProps {
  /** The cached document's id: progress is stored under it, per learner. */
  storyId: string;
  /** The signed-in learner; without one, progress is neither read nor saved. */
  userId: string | null;
  /**
   * The story, personalised for this learner, with `{friend}` still in it:
   * the player asks for the friend's name and fills it in itself.
   */
  story: StoryCourse;
  moduleId: string;
  language: 'fr' | 'en';
}

/** The chapter that was just played to its end. */
interface FinishedChapter {
  index: number;
  points: number;
  maxPoints: number;
}

/**
 * A loaded module story: the chapter index, one chapter's player at a time,
 * resume from this browser's progress, per-chapter lesson completion, and
 * the end-of-module summary.
 */
function ModuleStoryReader({ storyId, userId, story, moduleId, language }: ReaderProps) {
  const t = useTranslations('ModuleStory');
  const target = story.languages?.target ?? 'en';
  const home = story.languages?.home ?? 'fr';
  const chapters = story.chapters;

  // This panel's own headings (the title, the chapter list, the still-to-do
  // list) carry the friend's name too: the one chosen on the start card, else
  // the cast's default, else the generic word.
  const [friend, setFriend] = useState(() => readChoices(choicesKeyFor(story))?.friend);
  const shown = useMemo(
    () => personalizeStory(story, { friend, language }),
    [story, friend, language],
  );
  const shownChapters = useMemo(
    () => new Map(shown.chapters.map((chapter) => [chapter.id, chapter.title])),
    [shown],
  );

  // Resume at the first chapter not finished in this browser; -1 is the
  // summary (every chapter done).
  const [initial] = useState(() => {
    const saved = readStoryProgress(storyId, userId);
    return { progress: saved, selected: firstIncompleteChapter(chapters, saved) };
  });
  const [progress, setProgress] = useState<StoryProgress>(initial.progress);
  const progressRef = useRef(initial.progress);
  // Note which chapters this revision has, for the module page's story card
  // (which never loads the story): it counts only these (#2682).
  const revision = story.module_story?.revision;
  useEffect(() => {
    const next = withChapterSnapshot(progressRef.current, chapters, revision);
    if (next === progressRef.current) return;
    progressRef.current = next;
    writeStoryProgress(storyId, userId, next);
  }, [chapters, revision, storyId, userId]);
  const [selected, setSelected] = useState(initial.selected);
  // Bumped on every chapter opened, so replaying the open chapter restarts it.
  const [run, setRun] = useState(0);
  const [finished, setFinished] = useState<FinishedChapter | null>(null);

  // Units the server lists as completed (matched on module unit id), plus the
  // ones this page has recorded since. Best effort: offline it stays empty.
  const [serverCompleted, setServerCompleted] = useState<ReadonlySet<string>>(() => new Set());
  const serverCompletedRef = useRef<ReadonlySet<string>>(new Set());
  // Whether that list was read: only the server can say every unit is done.
  const [serverRead, setServerRead] = useState(false);
  // Every unit of the module, as the server lists them. Some have no chapter
  // (a case study), and a quiz is only played as the rally, which does not
  // complete it: what is still to do comes from this list, not the chapters.
  const [serverUnits, setServerUnits] = useState<UnitProgressDetail[] | null>(null);
  // Lesson units whose completion this page posted and has not heard back on.
  const [posting, setPosting] = useState<ReadonlySet<string>>(() => new Set());
  const [recorded, setRecorded] = useState<ReadonlySet<string>>(() => new Set());
  // Completion is posted at most once per chapter, whatever happens to it.
  const postedRef = useRef<Set<string>>(new Set());
  const chapterLineRef = useRef<HTMLParagraphElement | null>(null);
  const doneRef = useRef<HTMLDivElement | null>(null);

  const markServerCompleted = useCallback((unitIds: Iterable<string>) => {
    const next = new Set(serverCompletedRef.current);
    for (const id of unitIds) next.add(id);
    serverCompletedRef.current = next;
    setServerCompleted(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    getModuleDetailWithProgress(moduleId)
      .then((detail) => {
        if (cancelled) return;
        const units = detail.units ?? [];
        markServerCompleted(units.filter((unit) => unit.status === 'completed').map((unit) => unit.id));
        setServerUnits([...units].sort((a, b) => a.order_index - b.order_index));
        setServerRead(true);
      })
      .catch(() => {
        // Offline or refused: completions are still posted, and a unit the
        // server already has completed is simply recorded again.
      });
    return () => {
      cancelled = true;
    };
  }, [moduleId, markServerCompleted]);

  const completedUnits = useMemo(() => new Set(progress.completedUnits), [progress]);
  // Scores are counted in the story's own unit (mangoes…), like the counter
  // in the player: one counter, one word for it.
  const unitLabel = text(story.rewards?.unit, target, home) || t('pointsWord');
  const totalMax = useMemo(() => {
    const fromCovers = chapters.reduce((sum, chapter) => sum + (chapter.covers?.max_points ?? 0), 0);
    if (chapters.some((chapter) => chapter.covers)) return fromCovers;
    return Number(story.checks?.max_points ?? 0);
  }, [chapters, story.checks]);
  // A saved score never counts for more than its chapter is worth now: the
  // best score is kept across revisions, and a regenerated chapter (or one
  // whose repeated questions another chapter's change dropped) can be worth less.
  const chapterPoints = (chapter: Chapter) => {
    const saved = progress.points[chapterKey(chapter)] ?? 0;
    return chapter.covers ? Math.min(saved, chapter.covers.max_points ?? 0) : saved;
  };
  const summed = chapters.reduce((sum, chapter) => sum + chapterPoints(chapter), 0);
  const totalPoints = totalMax > 0 ? Math.min(summed, totalMax) : summed;
  const doneCount = completedChapterCount(chapters, progress);
  const nextIncomplete = firstIncompleteChapter(chapters, progress);

  const openChapter = (index: number, review?: PlayerSnapshot) => {
    setSelected(index);
    setRun((n) => n + 1);
    setFinished(null);
    setReviewing(review ?? null);
    // Move focus to the "Chapter x of y" line once it shows the new chapter,
    // so keyboard and screen-reader users land at its start.
    requestAnimationFrame(() => chapterLineRef.current?.focus());
  };

  // What each chapter played on this page was answered with, so Previous
  // from the next chapter shows it again as it was (#2688).
  // Only a run that finished is kept for that (#2692): a replay left half way
  // must not replace it, and a chapter looked back at reports nothing.
  const snapshotsRef = useRef(new Map<string, PlayerSnapshot>());
  const liveSnapshotsRef = useRef(new Map<string, PlayerSnapshot>());
  const [reviewing, setReviewing] = useState<PlayerSnapshot | null>(null);

  // Previous on a chapter's first line: back to the last line of the one
  // before. A finished chapter comes back read-only (answered questions stay
  // answered, with their answers when they were given on this page; nothing
  // is scored or completed again) with its end card and its best score; one
  // not finished yet is simply opened.
  const backIntoChapterBefore = (index: number) => {
    const before = chapters[index - 1];
    if (!before) return;
    if (!completedUnits.has(chapterKey(before))) {
      openChapter(index - 1);
      return;
    }
    const maxPoints = before.covers?.max_points ?? 0;
    const saved = chapterPoints(before);
    const best = maxPoints > 0 ? Math.min(saved, maxPoints) : saved;
    const snapshot = snapshotsRef.current.get(before.id);
    openChapter(index - 1, { records: snapshot?.records ?? [], points: best });
    setFinished({ index: index - 1, points: best, maxPoints });
  };

  const showSummary = () => {
    setSelected(-1);
    setFinished(null);
    requestAnimationFrame(() => chapterLineRef.current?.focus());
  };

  const handleChapterComplete = (
    index: number,
    outcome: { points: number; maxPoints: number },
  ) => {
    const chapter = chapters[index];
    if (!chapter) return;
    // This run finished: it is what Previous will show of the chapter.
    const live = liveSnapshotsRef.current.get(chapter.id);
    if (live) snapshotsRef.current.set(chapter.id, live);

    const next = withChapterDone(progressRef.current, chapterKey(chapter), outcome.points);
    progressRef.current = next;
    setProgress(next);
    writeStoryProgress(storyId, userId, next);
    setFinished({ index, points: outcome.points, maxPoints: outcome.maxPoints });
    // Bring "Chapter complete" and its Next button into view on a phone.
    // (Optional call: jsdom and some old WebViews lack scrollIntoView.)
    requestAnimationFrame(() =>
      doneRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }),
    );

    // A finished lesson chapter completes its lesson unit, once. Quiz and
    // case-study units still need their own attempt, and story points never
    // become a quiz score.
    const covers = chapter.covers;
    if (!covers?.completes_unit) return;
    if (serverCompletedRef.current.has(covers.module_unit_id)) return;
    if (postedRef.current.has(chapter.id)) return;
    postedRef.current.add(chapter.id);
    const unitId = covers.module_unit_id;
    const settled = () =>
      setPosting((prev) => {
        const next = new Set(prev);
        next.delete(unitId);
        return next;
      });
    setPosting((prev) => new Set(prev).add(unitId));
    completeLessonUnit(moduleId, covers.unit_number, { online: isOnline() })
      .then(() => {
        markServerCompleted([unitId]);
        setRecorded((prev) => new Set(prev).add(unitId));
      })
      .catch((err) => {
        console.error('Could not record the lesson from the module story:', err);
      })
      .finally(settled);
  };

  const chapter = selected >= 0 ? chapters[selected] : undefined;
  const moduleNumber = story.module_story?.module_number ?? story.week;
  const done = finished && finished.index === selected ? finished : null;

  const chapterTitle = (c: Chapter) => text(shownChapters.get(c.id) ?? c.title, target, home);
  const kindLabel = (c: Chapter) => {
    const label = t('kind', { kind: chapterKind(c.covers) });
    return c.covers?.unit_number ? `${label} ${c.covers.unit_number}` : label;
  };
  const unitHref = (covers: ChapterCovers) =>
    `/modules/${moduleId}/units/${encodeURIComponent(covers.unit_number)}`;
  const hrefFor = (unitNumber: string) => `/modules/${moduleId}/units/${encodeURIComponent(unitNumber)}`;

  // Still to do once the story is over. With the server's unit list: every
  // unit it does not have completed, whether or not the story has a chapter
  // for it (a case study has none; the quiz is only played as the rally),
  // except a lesson whose completion this page is posting right now. Without
  // it (offline): the units the story cannot complete itself.
  const chapterFor = (unitId: string) =>
    chapters.find((c) => c.covers?.module_unit_id === unitId && !c.covers.rally) ??
    chapters.find((c) => c.covers?.module_unit_id === unitId);
  // An empty list says nothing about this module's units: it is read as no
  // list at all (#2682), never as "every unit is done".
  const knownUnits = serverUnits && serverUnits.length > 0 ? serverUnits : null;
  const stillToDo: Array<{ id: string; number: string; kind: UnitKind; title: string }> = knownUnits
    ? knownUnits
        .filter((unit) => !serverCompleted.has(unit.id) && !posting.has(unit.id))
        .map((unit) => {
          const covering = chapterFor(unit.id);
          const kind: UnitKind =
            unit.unit_type === 'quiz'
              ? 'quiz'
              : unit.unit_type === 'case-study' || unit.unit_type === 'scenario'
                ? 'case'
                : unit.unit_type === 'lesson'
                  ? 'lesson'
                  : unitKind(covering?.covers);
          const title = covering && !covering.covers?.rally
            ? chapterTitle(covering)
            : (language === 'fr' ? unit.title_fr : unit.title_en) || unit.title_fr || unit.title_en;
          return { id: unit.id, number: unit.unit_number, kind, title };
        })
    : chapters
        .filter((c) => c.covers && !serverCompleted.has(c.covers.module_unit_id) && sendsToUnit(c.covers))
        .map((c) => ({
          id: c.covers!.module_unit_id,
          number: c.covers!.unit_number,
          kind: unitKind(c.covers),
          title: chapterTitle(c),
        }))
        .filter((item, index, list) => list.findIndex((other) => other.id === item.id) === index);
  // "Every unit is done" is the server's word, never this browser's alone.
  const allDone = serverRead && !!knownUnits && knownUnits.every((unit) => serverCompleted.has(unit.id));
  const moduleStars = starsFor(totalMax ? totalPoints / totalMax : 0, story.rewards?.stars);

  return (
    <section aria-label={t('regionLabel')} className="mx-auto max-w-2xl">
      <header className="mb-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">
          {t('eyebrow', { number: moduleNumber })}
        </p>
        <div className="mt-1 flex items-start justify-between gap-3">
          <h1 className="min-w-0 text-xl font-bold text-gray-900 sm:text-2xl">
            {text(shown.title, target, home)}
          </h1>
          {chapters.length > 0 ? (
            <p className="shrink-0 pt-1 text-sm font-semibold text-teal-700">
              {t('chaptersProgress', { done: doneCount, total: chapters.length })}
            </p>
          ) : null}
        </div>
      </header>

      <details
        // Open on the summary, folded away while a chapter plays so the story
        // starts near the top of a phone screen.
        key={selected === -1 ? 'summary' : 'playing'}
        open={selected === -1}
        className="mb-4 rounded-lg border border-gray-200 bg-white"
      >
        <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-2 px-3 text-sm font-semibold text-gray-800">
          <span>{t('chapters')}</span>
          <span className="font-normal text-gray-600">
            {doneCount}/{chapters.length}
          </span>
        </summary>
        <nav aria-label={t('chapters')}>
          <ol className="divide-y divide-gray-100 border-t border-gray-100">
            {chapters.map((c, index) => {
              const isDone = completedUnits.has(chapterKey(c));
              const isCurrent = index === selected;
              const reachable = isDone || isCurrent || index === nextIncomplete;
              const max = c.covers?.max_points ?? 0;
              const points = chapterPoints(c);
              const state = isCurrent
                ? t('chapterCurrent')
                : isDone
                  ? t('chapterDone')
                  : t('chapterUpcoming');
              const body = (
                <>
                  <span
                    aria-hidden="true"
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      isDone
                        ? 'bg-teal-600 text-white'
                        : isCurrent
                          ? 'border-2 border-teal-600 text-teal-700'
                          : 'border border-gray-300 text-gray-500'
                    }`}
                  >
                    {isDone ? '✓' : index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-gray-900">{chapterTitle(c)}</span>
                    <span className="block text-xs text-gray-600">
                      {kindLabel(c)}
                      <span className="sr-only">{` · ${state}`}</span>
                    </span>
                  </span>
                  {isDone && max > 0 ? (
                    <span className="shrink-0 text-xs font-semibold text-teal-700">
                      {points}/{max}
                    </span>
                  ) : null}
                </>
              );
              return (
                <li key={c.id}>
                  {reachable ? (
                    <button
                      type="button"
                      onClick={() => openChapter(index)}
                      aria-current={isCurrent ? 'step' : undefined}
                      className={`flex min-h-11 w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-500 ${
                        isCurrent ? 'bg-teal-50' : ''
                      }`}
                    >
                      {body}
                    </button>
                  ) : (
                    <div className="flex min-h-11 items-center gap-3 px-3 py-2 text-sm">
                      {body}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      </details>

      <p
        ref={chapterLineRef}
        tabIndex={-1}
        className="mb-2 text-sm font-semibold text-gray-700 focus:outline-none"
      >
        {chapter
          ? t('chapterOf', { current: selected + 1, total: chapters.length })
          : t('moduleComplete')}
      </p>

      {chapter ? (
        <div>
          <StoryPlayer
            key={`${chapter.id}:${run}`}
            course={story}
            chapterId={chapter.id}
            maxPoints={chapter.covers?.max_points ?? 0}
            hideFinishSummary
            variant="embedded"
            onComplete={(outcome) => handleChapterComplete(selected, outcome)}
            onStart={(choices) => setFriend(choices.friend)}
            review={reviewing ?? undefined}
            onSnapshot={(snapshot) => liveSnapshotsRef.current.set(chapter.id, snapshot)}
            onBackFromStart={selected > 0 ? () => backIntoChapterBefore(selected) : undefined}
          />

          {sendsToUnit(chapter.covers) ? (
            <Link
              href={unitHref(chapter.covers)}
              className="mt-4 flex min-h-11 items-center justify-center gap-2 rounded-lg border border-teal-600 px-4 text-sm font-semibold text-teal-800 hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              {t('openUnit', { kind: unitKind(chapter.covers), number: chapter.covers.unit_number })}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          ) : null}

          {done ? (
            <div
              ref={doneRef}
              role="status"
              className="mt-6 rounded-xl border border-teal-200 bg-teal-50 p-4 text-center"
            >
              <p className="font-semibold text-gray-900">{t('chapterComplete')}</p>
              {done.maxPoints > 0 ? (
                <p className="text-sm text-gray-700">
                  {t('scoreIn', { points: done.points, max: done.maxPoints, unit: unitLabel })}
                </p>
              ) : null}
              {chapter.covers && recorded.has(chapter.covers.module_unit_id) ? (
                <p className="mt-1 flex items-center justify-center gap-1 text-sm text-teal-800">
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  {t('lessonRecorded', { number: chapter.covers.unit_number })}
                </p>
              ) : null}
              {nextIncomplete >= 0 ? (
                <Button
                  type="button"
                  onClick={() => openChapter(nextIncomplete)}
                  className="mt-3 min-h-11 w-full bg-teal-600 hover:bg-teal-700"
                >
                  {t('nextChapter')}
                </Button>
              ) : (
                <Button
                  type="button"
                  onClick={showSummary}
                  className="mt-3 min-h-11 w-full bg-teal-600 hover:bg-teal-700"
                >
                  {t('seeSummary')}
                </Button>
              )}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-xl border border-teal-200 bg-white p-4">
          <div className="text-center" role="status">
            {moduleStars > 0 ? (
              <p className="text-lg font-bold" aria-hidden="true">
                {'⭐'.repeat(moduleStars)}
              </p>
            ) : null}
            <p className="text-sm text-gray-700">
              {totalMax > 0
                ? t('scoreIn', { points: totalPoints, max: totalMax, unit: unitLabel })
                : t('pointsIn', { points: totalPoints, unit: unitLabel })}
            </p>
          </div>

          {stillToDo.length > 0 ? (
            <div className="mt-4">
              <h2 className="font-semibold text-gray-900">{t('stillToDo')}</h2>
              <p className="mt-1 text-sm text-gray-600">{t('stillToDoHint')}</p>
              <ul className="mt-3 space-y-2">
                {stillToDo.map((unit) => (
                  <li key={unit.id}>
                    <Link
                      href={hrefFor(unit.number)}
                      className="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm hover:border-teal-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                    >
                      <span className="min-w-0">
                        <span className="block font-semibold text-teal-800">
                          {t('openUnit', { kind: unit.kind, number: unit.number })}
                        </span>
                        <span className="block truncate text-gray-700">{unit.title}</span>
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-teal-700" aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : allDone ? (
            <p className="mt-4 flex items-center justify-center gap-2 text-sm text-teal-800">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              {t('allDone')}
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
