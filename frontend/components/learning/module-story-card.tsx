'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { BookOpen, ChevronRight, Loader2, Lock } from 'lucide-react';

import { Link } from '@/i18n/routing';
import { ApiError } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { getModuleStoryStatus } from '@/lib/story-course/api';
import { moduleStoryId, readStoryProgress, storyStanding } from '@/lib/story-course/progress';
import type { ModuleStoryStatus } from '@/lib/story-course/types';

type CardState =
  | { kind: 'loading' }
  | { kind: 'hidden' }
  | { kind: 'start' }
  | { kind: 'resume'; current: number; total: number }
  | { kind: 'done' }
  | { kind: 'generating' }
  | { kind: 'subscribersOnly' }
  | { kind: 'unavailable' };

/**
 * Start, resume or done, from this learner's progress here and the status.
 * Only chapters of the revision the server serves now count (#2682): a key
 * left over from an older revision (a checkpoint the rally replaced) must not
 * make a story look further along, or finished, than it is.
 */
function fromProgress(
  storyId: string,
  userId: string | null,
  status: Pick<ModuleStoryStatus, 'chapters' | 'revision'> | null,
): CardState {
  const { completed, total, certain } = storyStanding(readStoryProgress(storyId, userId), status);
  if (total <= 0 || completed <= 0) return { kind: 'start' };
  if (certain && completed >= total) return { kind: 'done' };
  return { kind: 'resume', current: Math.min(completed + 1, total), total };
}

function cardStateFor(
  status: ModuleStoryStatus,
  storyId: string,
  userId: string | null,
): CardState {
  if (status.state === 'disabled') return { kind: 'hidden' };
  if (status.access === 'subscription_required') return { kind: 'subscribersOnly' };
  switch (status.state) {
    case 'unavailable':
      return { kind: 'unavailable' };
    case 'generating':
      return { kind: 'generating' };
    default:
      // ready, or not_ready (opening it writes the story).
      return fromProgress(storyId, userId, status);
  }
}

interface ModuleStoryCardProps {
  moduleId: string;
  language: 'fr' | 'en';
}

/**
 * The module page's way into the module story: one full-width link, with a
 * line that says where the learner is (start, continue chapter x of y, done,
 * being written, subscribers only).
 *
 * It asks the status route, which never generates anything and never sends
 * the story itself, and reads this browser's progress. The story player is
 * not imported here: it loads only on the story route.
 */
export function ModuleStoryCard({ moduleId, language }: ModuleStoryCardProps) {
  const t = useTranslations('ModuleOverview.storyCard');
  const { user, isHydrated } = useCurrentUser();
  const userId = user?.id ?? null;
  const [state, setState] = useState<CardState>({ kind: 'loading' });

  useEffect(() => {
    // The progress line is this learner's: wait for the signed-in user.
    if (!isHydrated) return;
    let cancelled = false;
    const storyId = moduleStoryId(moduleId, language);
    getModuleStoryStatus(moduleId, language)
      .then((status) => {
        if (!cancelled) setState(cardStateFor(status, storyId, userId));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // No such module (or no status route on this server): no card.
        if (err instanceof ApiError && err.status === 404) {
          setState({ kind: 'hidden' });
          return;
        }
        // Offline or a server error: the link still works for a downloaded
        // story, so offer it from what this browser knows.
        setState(fromProgress(storyId, userId, null));
      });
    return () => {
      cancelled = true;
    };
  }, [moduleId, language, isHydrated, userId]);

  if (state.kind === 'loading' || state.kind === 'hidden') return null;

  const line =
    state.kind === 'resume'
      ? t('resume', { current: state.current, total: state.total })
      : t(state.kind);
  const Icon =
    state.kind === 'subscribersOnly' ? Lock : state.kind === 'generating' ? Loader2 : BookOpen;

  return (
    <div className="mb-8">
      <Link
        href={`/modules/${moduleId}/story`}
        className="flex min-h-11 w-full items-center gap-3 rounded-xl border border-teal-200 bg-teal-50 p-4 text-left transition-colors hover:border-teal-400 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2"
      >
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-teal-700 text-white"
          aria-hidden="true"
        >
          <Icon className={`h-5 w-5 ${state.kind === 'generating' ? 'animate-spin' : ''}`} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-stone-900">{t('title')}</span>
          <span className="block text-sm text-stone-700">{line}</span>
        </span>
        <ChevronRight className="h-5 w-5 shrink-0 text-teal-700" aria-hidden="true" />
      </Link>
    </div>
  );
}
