'use client';

import { authClient } from '@/lib/auth';

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface UploadedFile {
  file_id: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  expires_at: string;
}

export async function uploadTutorFile(
  file: File,
  onProgress?: (percent: number) => void
): Promise<UploadedFile> {
  const token = await authClient.getValidToken();
  const formData = new FormData();
  formData.append('file', file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/api/v1/tutor/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadedFile);
        } catch {
          reject(new Error('Invalid response from server'));
        }
      } else if (xhr.status === 429) {
        reject(new Error('DAILY_LIMIT_REACHED'));
      } else {
        try {
          const err = JSON.parse(xhr.responseText);
          reject(new Error(err.detail || 'Upload failed'));
        } catch {
          reject(new Error(`Upload failed: ${xhr.status}`));
        }
      }
    };

    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(formData);
  });
}

const CACHE_KEY_CONVERSATIONS = 'tutor_conversations_cache';
const CACHE_KEY_PREFIX_CONVERSATION = 'tutor_conversation_';
const CACHE_TTL_MS = 5 * 60 * 1000;

export interface ConversationSummary {
  id: string;
  module_id: string | null;
  message_count: number;
  last_message_at: string;
  preview: string;
}

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  sources: Array<{ source: string; chapter?: number; page?: number }>;
  timestamp: string;
  activity_suggestions: Array<{ type: string; label: string; url?: string }>;
}

export interface ConversationDetail {
  id: string;
  module_id: string | null;
  messages: ConversationMessage[];
  created_at: string;
}

interface CachedData<T> {
  data: T;
  cached_at: number;
}

function getCached<T>(key: string): T | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed: CachedData<T> = JSON.parse(raw);
    if (Date.now() - parsed.cached_at > CACHE_TTL_MS) {
      localStorage.removeItem(key);
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
}

function setCache<T>(key: string, data: T): void {
  if (typeof window === 'undefined') return;
  try {
    const payload: CachedData<T> = { data, cached_at: Date.now() };
    localStorage.setItem(key, JSON.stringify(payload));
  } catch {
    // Ignore storage quota errors
  }
}

function clearCache(key: string): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore
  }
}

export async function fetchConversations(
  options: { limit?: number; offset?: number } = {}
): Promise<{ conversations: ConversationSummary[]; total: number }> {
  const { limit = 20, offset = 0 } = options;

  const cached = getCached<{ conversations: ConversationSummary[]; total: number }>(
    CACHE_KEY_CONVERSATIONS
  );
  if (cached) return cached;

  const token = await authClient.getValidToken();
  const response = await fetch(
    `${API_BASE}/api/v1/tutor/conversations?limit=${limit}&offset=${offset}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.status}`);
  }

  const data = await response.json();
  setCache(CACHE_KEY_CONVERSATIONS, data);
  return data;
}

export async function fetchConversation(conversationId: string): Promise<ConversationDetail> {
  const cacheKey = `${CACHE_KEY_PREFIX_CONVERSATION}${conversationId}`;
  const cached = getCached<ConversationDetail>(cacheKey);
  if (cached) return cached;

  const token = await authClient.getValidToken();
  const response = await fetch(`${API_BASE}/api/v1/tutor/conversations/${conversationId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch conversation: ${response.status}`);
  }

  const data = await response.json();
  setCache(cacheKey, data);
  return data;
}

export function invalidateConversationsCache(): void {
  clearCache(CACHE_KEY_CONVERSATIONS);
}

export function invalidateConversationCache(conversationId: string): void {
  clearCache(`${CACHE_KEY_PREFIX_CONVERSATION}${conversationId}`);
}

export function getOfflineConversations(): { conversations: ConversationSummary[]; total: number } | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY_CONVERSATIONS);
    if (!raw) return null;
    const parsed: CachedData<{ conversations: ConversationSummary[]; total: number }> = JSON.parse(raw);
    return parsed.data;
  } catch {
    return null;
  }
}

export function getOfflineConversation(conversationId: string): ConversationDetail | null {
  try {
    const raw = localStorage.getItem(`${CACHE_KEY_PREFIX_CONVERSATION}${conversationId}`);
    if (!raw) return null;
    const parsed: CachedData<ConversationDetail> = JSON.parse(raw);
    return parsed.data;
  } catch {
    return null;
  }
}

export interface TutorStats {
  daily_messages_used: number;
  daily_messages_limit: number;
  total_conversations: number;
  most_discussed_topics: string[];
}

export async function fetchTutorStats(): Promise<TutorStats> {
  const token = await authClient.getValidToken();
  const response = await fetch(`${API_BASE}/api/v1/tutor/stats`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch tutor stats: ${response.status}`);
  }

  return response.json();
}
