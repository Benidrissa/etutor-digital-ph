/**
 * Recording that a learner finished a lesson unit — by the "Mark complete"
 * button, or by finishing that lesson's chapter of the module story (once
 * per chapter; quiz and case-study chapters never complete their unit).
 *
 * On 2G `navigator.onLine` is often true while requests still die, so being
 * "online" is not enough to trust the POST. When the request never gets an
 * answer, or the server fails, the completion is queued for background sync
 * exactly as it is offline, instead of being dropped. A 4xx is the server
 * refusing the completion: replaying it would only fail again, so it is
 * reported and nothing is queued.
 *
 * "Never gets an answer" includes a stalled link: the connection stays open
 * and nothing comes back, and the browser can take minutes to give up. So the
 * POST has a deadline (COMPLETION_TIMEOUT_MS); past it the request is aborted
 * and the completion is queued like any other transient failure.
 *
 * Offline, the queue is replayed on the next `online` event. A completion
 * queued while the device still looked online gets no such event, so it asks
 * the sync manager for a replay on a short backoff instead.
 */

import { apiFetch } from '@/lib/api';
import { addOfflineAction, requestOfflineReplay } from '@/lib/offline/db';

export type LessonCompletion = 'recorded' | 'queued';

/** How long the completion POST may take before it is given up and queued. */
export const COMPLETION_TIMEOUT_MS = 15_000;

/**
 * True for a failure worth replaying later: the request did not get through
 * (fetch's TypeError — "Failed to fetch", Safari's "Load failed"), it timed
 * out, or the server answered 5xx. False for a 4xx and anything else.
 */
export function isTransientFailure(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  if (
    typeof DOMException !== 'undefined' &&
    err instanceof DOMException &&
    (err.name === 'TimeoutError' || err.name === 'NetworkError')
  ) {
    return true;
  }
  if (err && typeof err === 'object' && 'status' in err) {
    const status = (err as { status: unknown }).status;
    return typeof status === 'number' && status >= 500;
  }
  return false;
}

function timeoutError(): DOMException {
  return new DOMException('The completion request timed out.', 'TimeoutError');
}

/**
 * A signal that aborts after `ms`: `AbortSignal.timeout` where the browser has
 * it, else an AbortController on a timer. `clear` stops the fallback timer; the
 * native one cannot be stopped, and firing after the POST settled is harmless.
 */
function deadlineSignal(ms: number): { signal: AbortSignal; clear: () => void } {
  if (typeof AbortSignal.timeout === 'function') {
    return { signal: AbortSignal.timeout(ms), clear: () => {} };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(timeoutError()), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

/**
 * POST the completion, failing with a TimeoutError at the deadline.
 *
 * The signal aborts the fetch, so nothing is still sent once the completion
 * has been queued. The race covers the whole call, not only the fetch: the
 * token refresh that may run before it has no deadline of its own.
 */
async function postCompletion(moduleId: string, unitId: string): Promise<void> {
  const { signal, clear } = deadlineSignal(COMPLETION_TIMEOUT_MS);
  let onAbort = () => {};
  const expired = new Promise<never>((_, reject) => {
    onAbort = () => reject(timeoutError());
    signal.addEventListener('abort', onAbort, { once: true });
  });
  try {
    await Promise.race([
      apiFetch('/api/v1/progress/complete-lesson', {
        method: 'POST',
        body: JSON.stringify({ module_id: moduleId, unit_id: unitId }),
        signal,
      }),
      expired,
    ]);
  } catch (err) {
    // Past the deadline the failure is the timeout, whatever the aborted
    // fetch threw (a plain AbortError where abort reasons are unsupported).
    if (signal.aborted) throw timeoutError();
    throw err;
  } finally {
    signal.removeEventListener('abort', onAbort);
    clear();
  }
}

/** Queue the completion for the sync manager (replayed to complete-lesson). */
async function queueCompletion(moduleId: string, unitId: string): Promise<LessonCompletion> {
  await addOfflineAction({
    actionType: 'case_study_complete',
    payload: { module_id: moduleId, unit_id: unitId },
  });
  return 'queued';
}

/**
 * Record a lesson unit as complete: POST it when online, queue it when offline
 * or when the POST fails transiently or times out. Resolves once it is
 * recorded or queued, so the caller can show the unit as completed either way;
 * rejects on a 4xx (and on anything else unexpected), when nothing was queued.
 */
export async function completeLessonUnit(
  moduleId: string,
  unitId: string,
  { online }: { online: boolean },
): Promise<LessonCompletion> {
  if (!online) return queueCompletion(moduleId, unitId);
  try {
    await postCompletion(moduleId, unitId);
    return 'recorded';
  } catch (err) {
    if (!isTransientFailure(err)) throw err;
    const queued = await queueCompletion(moduleId, unitId);
    requestOfflineReplay();
    return queued;
  }
}
