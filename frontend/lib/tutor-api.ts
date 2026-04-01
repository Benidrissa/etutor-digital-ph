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
  activity_suggestions: Array<{ type: string; title: string }>;
}

export interface ConversationDetail {
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
const CACHE_LIST_KEY = 'tutor_conversations_list';

export async function fetchConversations(limit = 20, offset = 0): Promise<ConversationListResponse> {
  const data = await apiFetch<ConversationListResponse>(
    `/api/v1/tutor/conversations?limit=${limit}&offset=${offset}`
  );
  try {
    localStorage.setItem(CACHE_LIST_KEY, JSON.stringify(data));
  } catch {
    // Storage quota exceeded or unavailable — ignore
  }
  return data;
}

export function getCachedConversationList(): ConversationListResponse | null {
  try {
    const raw = localStorage.getItem(CACHE_LIST_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ConversationListResponse;
  } catch {
    return null;
  }
}

export async function fetchConversation(conversationId: string): Promise<ConversationDetail> {
  const data = await apiFetch<ConversationDetail>(`/api/v1/tutor/conversations/${conversationId}`);
  try {
    localStorage.setItem(`${CACHE_KEY_PREFIX}${conversationId}`, JSON.stringify(data));
  } catch {
    // ignore
  }
  return data;
}

export function getCachedConversation(conversationId: string): ConversationDetail | null {
  try {
    const raw = localStorage.getItem(`${CACHE_KEY_PREFIX}${conversationId}`);
    if (!raw) return null;
    return JSON.parse(raw) as ConversationDetail;
  } catch {
    return null;
  }
}

export function cacheConversation(conversation: ConversationDetail): void {
  try {
    localStorage.setItem(`${CACHE_KEY_PREFIX}${conversation.id}`, JSON.stringify(conversation));
  } catch {
    // ignore
  }
}

export function updateCachedConversationList(summary: ConversationSummary): void {
  try {
    const cached = getCachedConversationList();
    if (!cached) return;
    const existing = cached.conversations.findIndex(c => c.id === summary.id);
    if (existing >= 0) {
      cached.conversations[existing] = summary;
    } else {
      cached.conversations.unshift(summary);
      cached.total += 1;
    }
    localStorage.setItem(CACHE_LIST_KEY, JSON.stringify(cached));
  } catch {
    // ignore
  }
}
