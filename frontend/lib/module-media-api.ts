import { apiFetch } from './api';

export type MediaType = 'audio_summary' | 'video_summary';
export type MediaStatus = 'pending' | 'generating' | 'ready' | 'failed';

export interface ModuleMediaRecord {
  id: string;
  module_id: string;
  media_type: MediaType;
  language: string;
  status: MediaStatus;
  url: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  mime_type: string | null;
  generated_at: string | null;
  created_at: string;
}

export interface ModuleMediaListResponse {
  module_id: string;
  media: ModuleMediaRecord[];
  total: number;
}

export interface GenerateMediaResponse {
  media_id: string;
  task_id: string | null;
  status: MediaStatus;
  message: string;
}

export interface MediaStatusResponse {
  media_id: string;
  status: MediaStatus;
  url: string | null;
}

export async function getModuleMedia(moduleId: string): Promise<ModuleMediaListResponse> {
  return apiFetch<ModuleMediaListResponse>(`/api/v1/modules/${moduleId}/media`);
}

export async function generateModuleMedia(
  moduleId: string,
  mediaType: MediaType,
  language: string,
  forceRegenerate = false
): Promise<GenerateMediaResponse> {
  return apiFetch<GenerateMediaResponse>(`/api/v1/modules/${moduleId}/media/generate`, {
    method: 'POST',
    body: JSON.stringify({
      media_type: mediaType,
      language,
      force_regenerate: forceRegenerate,
    }),
  });
}

export async function pollMediaStatus(
  moduleId: string,
  mediaId: string
): Promise<MediaStatusResponse> {
  return apiFetch<MediaStatusResponse>(
    `/api/v1/modules/${moduleId}/media/${mediaId}/status`
  );
}
