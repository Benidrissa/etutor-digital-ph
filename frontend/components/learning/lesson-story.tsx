'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { AlertTriangle, Loader2, RefreshCw, ScrollText, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StoryPlayer } from '@/components/story/story-player';
import { LessonStorySkeleton } from './lesson-story-skeleton';
import { apiFetch, ApiError } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { loadStory, OfflineContentNotAvailable } from '@/lib/offline/content-loader';
import {
  isStoryDocument,
  isStoryGenerating,
  isStoryUnavailableError,
  storyErrorCode,
} from '@/lib/story-course/api';
import { firstNameOf, personalizeStory } from '@/lib/story-course/personalize';
import type { StoryCourse } from '@/lib/story-course/types';

// Same cadence and cap as the lesson and quiz pollers.
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;
const UX_SLOW_WARNING_MS = 30 * 1000;

type PanelState =
  | { kind: 'loading' }
  | { kind: 'generating'; slow: boolean }
  | { kind: 'ready'; story: StoryCourse }
  /**
   * 409 story_unavailable (no story passing the validator could be written),
   * 404 not_a_lesson, or any other 403/404.
   */
  | { kind: 'unavailable' }
  /** detail.error story_mode_disabled (a 404): the backend has story mode off. */
  | { kind: 'disabled' }
  | { kind: 'offline' }
  | { kind: 'failed'; reason: 'failed' | 'timeout' };

interface ContentStatus {
  status: string;
  content_id?: string;
  error?: string;
}

interface LessonStoryProps {
  moduleId: string;
  unitId: string;
  /** The lesson's language; the story is generated and cached per language. */
  language: 'fr' | 'en';
  /**
   * True while the Story tab is the open tab. Every lesson tab is kept
   * mounted (audio continuity), so without this the panel would download a
   * whole story document on every lesson view — on 2G — before anyone asked
   * for it. Nothing is fetched until the tab is first opened; after that the
   * panel keeps its story (and the learner's place in it) across tab switches.
   */
  active: boolean;
  /** Lifted while the story is being written, so the tab can show a badge. */
  onActivelyGeneratingChange?: (generating: boolean) => void;
  /**
   * Fires once when the learner reaches the end of the story. The lesson
   * viewer records completion of this lesson unit through its usual path.
   */
  onComplete?: () => void;
}

/**
 * The lesson's Story tab: the lesson retold as a story-course/1 week in which
 * the learner is the hero.
 *
 * GET /api/v1/story-courses/unit/{module}/{unit}?language= answers 200 with
 * the story, 202 while it is being written (polled on the shared
 * /content/status endpoint, as lessons and quizzes are), or 409 when no valid
 * story could be generated. Reads go through the offline loader, so a
 * downloaded module's story opens with no network.
 */
export function LessonStory({
  moduleId,
  unitId,
  language,
  active,
  onActivelyGeneratingChange,
  onComplete,
}: LessonStoryProps) {
  const t = useTranslations('LessonStory');
  const { user, isHydrated } = useCurrentUser();

  // Latches on the first time the tab is opened (state adjusted during render,
  // not in an effect, so the fetch starts in the same commit).
  const [armed, setArmed] = useState(active);
  if (active && !armed) setArmed(true);

  const [state, setState] = useState<PanelState>({ kind: 'loading' });
  // Bumped by the Retry button to re-run the fetch. A counter only moves on a
  // click, so unlike a `forceRegenerate` flag kept in state it cannot loop.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Wait for the localStorage-backed user, like the lesson viewer: the
    // story needs the learner's name, and fetching before hydration is how
    // the viewers once dispatched duplicate generation tasks.
    if (!armed || !isHydrated) return;

    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let slowTimer: ReturnType<typeof setTimeout> | null = null;

    function settle(next: PanelState) {
      if (cancelled) return;
      if (slowTimer) {
        clearTimeout(slowTimer);
        slowTimer = null;
      }
      setState(next);
    }

    function fromError(err: unknown): PanelState {
      if (err instanceof OfflineContentNotAvailable) return { kind: 'offline' };
      // The body's code decides first, whatever the status (contract X2):
      // switched off is a 404 `story_mode_disabled`, not a 403.
      switch (storyErrorCode(err)) {
        case 'story_mode_disabled':
          return { kind: 'disabled' };
        case 'story_unavailable':
        case 'not_a_lesson':
          return { kind: 'unavailable' };
      }
      if (isStoryUnavailableError(err)) return { kind: 'unavailable' };
      // Any other 403/404 (a paywall, a unit that is gone) is not "switched
      // off": the lesson simply has no story to show.
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        return { kind: 'unavailable' };
      }
      return { kind: 'failed', reason: 'failed' };
    }

    /** Show the story, or keep polling while the endpoint still says "generating". */
    function accept(data: unknown, taskId: string, startedAt: number) {
      if (isStoryGenerating(data)) {
        poll(data.task_id || taskId, startedAt);
        return;
      }
      // Defensive: never hand the player an envelope or an error body.
      settle(isStoryDocument(data) ? { kind: 'ready', story: data } : { kind: 'failed', reason: 'failed' });
    }

    function poll(taskId: string, startedAt: number) {
      pollTimer = setTimeout(async () => {
        if (cancelled) return;
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          settle({ kind: 'failed', reason: 'timeout' });
          return;
        }
        try {
          const status = await apiFetch<ContentStatus>(`/api/v1/content/status/${taskId}`);
          if (cancelled) return;
          if (status.status === 'complete') {
            // Re-read through the loader so the finished story is cached
            // for offline use like any other fetch.
            const { data } = await loadStory<unknown>(moduleId, unitId, language);
            if (cancelled) return;
            accept(data, taskId, startedAt);
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
        const { data } = await loadStory<unknown>(moduleId, unitId, language);
        if (cancelled) return;
        if (isStoryGenerating(data)) {
          // Without a task id we would poll /content/status/undefined forever.
          if (!data.task_id) {
            settle({ kind: 'failed', reason: 'failed' });
            return;
          }
          setState({ kind: 'generating', slow: false });
          slowTimer = setTimeout(() => {
            if (cancelled) return;
            setState((prev) => (prev.kind === 'generating' ? { kind: 'generating', slow: true } : prev));
          }, UX_SLOW_WARNING_MS);
          poll(data.task_id, Date.now());
          return;
        }
        accept(data, '', Date.now());
      } catch (err) {
        if (!cancelled) settle(fromError(err));
      }
    }

    void run();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (slowTimer) clearTimeout(slowTimer);
    };
    // `state` is deliberately not a dependency: a status flip would restart
    // the fetch and kill the poll timer (the quiz container's infinite loop).
  }, [armed, isHydrated, moduleId, unitId, language, attempt]);

  // Lift "generating" to the tab badge; the ref spares the parent a useCallback.
  const onGeneratingRef = useRef(onActivelyGeneratingChange);
  useEffect(() => {
    onGeneratingRef.current = onActivelyGeneratingChange;
  }, [onActivelyGeneratingChange]);
  const isGenerating = state.kind === 'generating';
  useEffect(() => {
    onGeneratingRef.current?.(isGenerating);
  }, [isGenerating]);
  useEffect(() => () => onGeneratingRef.current?.(false), []);

  // Completion is reported once per panel, however often the player calls.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);
  const completedRef = useRef(false);
  const handleComplete = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    onCompleteRef.current?.();
  }, []);

  // C4: one cached story serves every learner; their first name goes in at
  // display time, on a copy, so the cached document stays name-free.
  const firstName = firstNameOf(user?.name);
  const story = state.kind === 'ready' ? state.story : null;
  const personalized = useMemo(
    () => (story ? personalizeStory(story, { child: firstName, language }) : null),
    [story, firstName, language],
  );

  const retry = () => {
    setState({ kind: 'loading' });
    setAttempt((n) => n + 1);
  };

  if (!armed) return null;

  if (personalized) {
    return (
      <section aria-label={t('regionLabel')}>
        {/* `active` pauses a running mini-game while another tab is open. */}
        <StoryPlayer
          course={personalized}
          variant="embedded"
          active={active}
          onComplete={handleComplete}
        />
      </section>
    );
  }

  if (state.kind === 'loading' || state.kind === 'ready' || !isHydrated) {
    return <LessonStorySkeleton />;
  }

  if (state.kind === 'generating') {
    return (
      <div className="flex flex-col items-center py-10 text-center" role="status">
        <Loader2 className="mb-4 h-8 w-8 animate-spin text-teal-600" aria-hidden="true" />
        <p className="font-semibold text-gray-900">{t('generating')}</p>
        <p className="mt-1 max-w-md text-sm text-gray-600">{t('generatingDescription')}</p>
        {state.slow ? (
          <p className="mt-4 max-w-xs text-sm text-amber-700">{t('slowWarning')}</p>
        ) : null}
      </div>
    );
  }

  if (state.kind === 'unavailable' || state.kind === 'disabled') {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <ScrollText className="mb-3 h-8 w-8 text-stone-400" aria-hidden="true" />
        <p className="font-medium text-gray-900">
          {state.kind === 'unavailable' ? t('unavailable') : t('disabled')}
        </p>
        <p className="mt-1 max-w-md text-sm text-gray-600">{t('unavailableHint')}</p>
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
  );
}
