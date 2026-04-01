import { authClient, AuthError } from '@/lib/auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  activity_suggestions?: Array<{ type: string; label: string }>;
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

const CACHE_KEY = 'tutor_conversations_cache';
const CONVERSATION_CACHE_PREFIX = 'tutor_conv_';

export function getCachedConversations(): ConversationSummary[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ConversationSummary[];
  } catch {
    return [];
  }
}

export function setCachedConversations(conversations: ConversationSummary[]): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(conversations));
  } catch {
    // ignore storage errors
  }
}

export function getCachedConversation(id: string): ConversationDetail | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(`${CONVERSATION_CACHE_PREFIX}${id}`);
    if (!raw) return null;
    return JSON.parse(raw) as ConversationDetail;
  } catch {
    return null;
  }
}

export function setCachedConversation(conversation: ConversationDetail): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(
      `${CONVERSATION_CACHE_PREFIX}${conversation.id}`,
      JSON.stringify(conversation)
    );
  } catch {
    // ignore storage errors
  }
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const token = await authClient.getValidToken();
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

export async function fetchConversations(
  limit = 20,
  offset = 0
): Promise<ConversationListResponse> {
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/tutor/conversations?limit=${limit}&offset=${offset}`,
    { headers }
  );
  if (!response.ok) {
    throw new AuthError(`Failed to fetch conversations: ${response.status}`, response.status);
  }
  return response.json() as Promise<ConversationListResponse>;
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  const headers = await getAuthHeaders();
  const response = await fetch(`${API_BASE}/api/v1/tutor/conversations/${id}`, { headers });
  if (!response.ok) {
    throw new AuthError(`Failed to fetch conversation: ${response.status}`, response.status);
  }
  return response.json() as Promise<ConversationDetail>;
}
