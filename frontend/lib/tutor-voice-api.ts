/**
 * API helpers for tutor voice output (#1932). Split from tutor-api.ts so
 * the chat-panel tree-shakes cleanly when voice isn't used.
 */

import { API_BASE } from './api';
import { authClient } from './auth';

export type TutorAudioStatus = 'pending' | 'generating' | 'ready' | 'failed';

export interface TutorMessageAudioResponse {
  status: TutorAudioStatus;
  url: string | null;
  duration_seconds: number | null;
  error_message: string | null;
}

export interface VoiceSessionResponse {
  session_id: string;
  openai_session_id: string | null;
  client_secret: string;
  expires_at: string;
  model: string;
  minutes_used_today: number;
  minutes_cap_per_day: number;
}

export interface VoiceSessionCloseResponse {
  minutes_used_today: number;
  minutes_cap_per_day: number;
}

async function authedJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ data: T | null; status: number }> {
  const token = await authClient.getValidToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    return { data: null, status: response.status };
  }
  return { data: (await response.json()) as T, status: response.status };
}

export async function fetchTutorMessageAudio(
  conversationId: string,
  messageIndex: number,
  locale: 'fr' | 'en',
): Promise<{ data: TutorMessageAudioResponse | null; status: number }> {
  const qs = new URLSearchParams({ locale }).toString();
  return authedJson<TutorMessageAudioResponse>(
    `/api/v1/tutor/conversations/${conversationId}/messages/${messageIndex}/audio?${qs}`,
    { method: 'POST' },
  );
}

export async function startVoiceSession(
  locale: 'fr' | 'en',
): Promise<{ data: VoiceSessionResponse | null; status: number }> {
  return authedJson<VoiceSessionResponse>('/api/v1/tutor/voice-session', {
    method: 'POST',
    body: JSON.stringify({ locale }),
  });
}

export async function closeVoiceSession(
  sessionId: string,
  durationSeconds: number,
): Promise<{ data: VoiceSessionCloseResponse | null; status: number }> {
  return authedJson<VoiceSessionCloseResponse>(
    '/api/v1/tutor/voice-session/close',
    {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        duration_seconds: durationSeconds,
      }),
    },
  );
}
