/**
 * Recording that a learner finished a lesson unit — by the "Mark complete"
 * button or by reaching the end of the lesson's story.
 *
 * On 2G `navigator.onLine` is often true while requests still die, so being
 * "online" is not enough to trust the POST. When the request never gets an
 * answer, or the server fails, the completion is queued for background sync
 * exactly as it is offline, instead of being dropped. A 4xx is the server
 * refusing the completion: replaying it would only fail again, so it is
 * reported and nothing is queued.
 *
 * Offline, the queue is replayed on the next `online` event. A completion
 * queued while the device still looked online gets no such event, so it asks
 * the sync manager for a replay on a short backoff instead.
 */

import { apiFetch } from '@/lib/api';
import { addOfflineAction, requestOfflineReplay } from '@/lib/offline/db';

export type LessonCompletion = 'recorded' | 'queued';

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
 * or when the POST fails transiently. Resolves once it is recorded or queued,
 * so the caller can show the unit as completed either way; rejects on a 4xx
 * (and on anything else unexpected), when nothing was queued.
 */
export async function completeLessonUnit(
  moduleId: string,
  unitId: string,
  { online }: { online: boolean },
): Promise<LessonCompletion> {
  if (!online) return queueCompletion(moduleId, unitId);
  try {
    await apiFetch('/api/v1/progress/complete-lesson', {
      method: 'POST',
      body: JSON.stringify({ module_id: moduleId, unit_id: unitId }),
    });
    return 'recorded';
  } catch (err) {
    if (!isTransientFailure(err)) throw err;
    const queued = await queueCompletion(moduleId, unitId);
    requestOfflineReplay();
    return queued;
  }
}
