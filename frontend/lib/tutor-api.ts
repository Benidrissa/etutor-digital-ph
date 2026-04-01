import { apiFetch } from './api';

export interface ConversationSummary {
  id: string;
  module_id: string | null;
  message_count: number;
  last_message_at: string;
  preview: string;
}

export interface TutorMessage {
  role: 'user' | 'assistant';
  content: string;
  sources: Array<{ source: string; chapter?: number; page?: number }>;
  timestamp: string;
  activity_suggestions: Array<{ type: string; label: string }>;
}

export interface TutorConversation {
  id: string;
  module_id: string | null;
  messages: TutorMessage[];
  created_at: string;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
  total: number;
}

const CACHE_KEY_PREFIX = 'tutor_conv_';
const LIST_CACHE_KEY = 'tutor_conversations_list';

export async function fetchConversations(limit = 20, offset = 0): Promise<ConversationListResponse> {
  const result = await apiFetch<ConversationListResponse>(
    `/api/v1/tutor/conversations?limit=${limit}&offset=${offset}`
  );
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(LIST_CACHE_KEY, JSON.stringify(result));
    } catch {
      // localStorage might be unavailable (private mode, quota exceeded)
    }
  }
  return result;
}

export function getCachedConversationList(): ConversationListResponse | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(LIST_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ConversationListResponse;
  } catch {
    return null;
  }
}

export async function fetchConversation(conversationId: string): Promise<TutorConversation> {
  const result = await apiFetch<TutorConversation>(
    `/api/v1/tutor/conversations/${conversationId}`
  );
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(`${CACHE_KEY_PREFIX}${conversationId}`, JSON.stringify(result));
    } catch {
      // ignore
    }
  }
  return result;
}

export function getCachedConversation(conversationId: string): TutorConversation | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(`${CACHE_KEY_PREFIX}${conversationId}`);
    if (!raw) return null;
    return JSON.parse(raw) as TutorConversation;
  } catch {
    return null;
  }
}

export function cacheConversationMessages(conversationId: string, messages: TutorMessage[]): void {
  if (typeof window === 'undefined') return;
  try {
    const existing = getCachedConversation(conversationId);
    const updated: TutorConversation = existing
      ? { ...existing, messages }
      : { id: conversationId, module_id: null, messages, created_at: new Date().toISOString() };
    localStorage.setItem(`${CACHE_KEY_PREFIX}${conversationId}`, JSON.stringify(updated));
  } catch {
    // ignore
  }
}

export function updateCachedConversationList(summary: ConversationSummary): void {
  if (typeof window === 'undefined') return;
  try {
    const cached = getCachedConversationList();
    if (!cached) return;
    const exists = cached.conversations.some(c => c.id === summary.id);
    const updated: ConversationListResponse = {
      conversations: exists
        ? cached.conversations.map(c => (c.id === summary.id ? summary : c))
        : [summary, ...cached.conversations],
      total: exists ? cached.total : cached.total + 1,
    };
    localStorage.setItem(LIST_CACHE_KEY, JSON.stringify(updated));
  } catch {
    // ignore
  }
}
