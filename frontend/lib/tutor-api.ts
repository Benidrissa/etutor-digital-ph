import { authClient, AuthError } from '@/lib/auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CACHE_KEY = 'tutor_conversations_cache';
const CACHE_TTL_MS = 5 * 60 * 1000;

export interface ConversationSummary {
  id: string;
  module_id: string | null;
  message_count: number;
  last_message_at: string;
  preview: string;
}

export interface ConversationMessage {
  role: string;
  content: string;
  sources: Record<string, unknown>[];
  timestamp: string;
  activity_suggestions: Record<string, string>[];
}

export interface ConversationDetail {
  id: string;
  module_id: string | null;
  messages: ConversationMessage[];
  created_at: string;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
  total: number;
}

interface CacheEntry<T> {
  data: T;
  ts: number;
}

function readCache<T>(key: string): T | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() - entry.ts > CACHE_TTL_MS) return null;
    return entry.data;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, data: T): void {
  if (typeof window === 'undefined') return;
  try {
    const entry: CacheEntry<T> = { data, ts: Date.now() };
    localStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // quota exceeded — silently skip
  }
}

function convDetailKey(id: string): string {
  return `tutor_conv_${id}`;
}

async function getToken(): Promise<string> {
  return authClient.getValidToken();
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const cached = readCache<ConversationSummary[]>(CACHE_KEY);

  try {
    const token = await getToken();
    const res = await fetch(`${API_BASE}/api/v1/tutor/conversations?limit=30`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new AuthError(`HTTP ${res.status}`, res.status);
    const data: ConversationListResponse = await res.json();
    writeCache(CACHE_KEY, data.conversations);
    return data.conversations;
  } catch (err) {
    if (cached) return cached;
    throw err;
  }
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  const cacheKey = convDetailKey(id);
  const cached = readCache<ConversationDetail>(cacheKey);

  try {
    const token = await getToken();
    const res = await fetch(`${API_BASE}/api/v1/tutor/conversations/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new AuthError(`HTTP ${res.status}`, res.status);
    const data: ConversationDetail = await res.json();
    writeCache(cacheKey, data);
    return data;
  } catch (err) {
    if (cached) return cached;
    throw err;
  }
}

export function invalidateConversationsCache(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(CACHE_KEY);
  } catch {
    // ignore
  }
}

export function cacheConversationDetail(detail: ConversationDetail): void {
  writeCache(convDetailKey(detail.id), detail);
}
