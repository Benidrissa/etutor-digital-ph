'use client';

import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Clock, BookOpen, Layers, Edit2, Plus, Mic, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { generateModuleMedia, type MediaStatus } from '@/lib/api';

export interface AdminModuleCardData {
  id: string;
  module_number: number;
  level: number;
  title_fr: string;
  title_en: string;
  description_fr?: string | null;
  description_en?: string | null;
  estimated_hours: number;
  bloom_level?: string | null;
  unit_count: number;
  source_references: string[];
  course_id?: string | null;
  course_title_fr?: string | null;
  course_title_en?: string | null;
  course_slug?: string | null;
}

interface AdminModuleCardProps {
  module: AdminModuleCardData;
  onEdit: (module: AdminModuleCardData) => void;
}

type AudioState = { status: MediaStatus } | null;

const LEVEL_LABELS: Record<number, { fr: string; en: string; color: string }> = {
  1: { fr: 'Débutant', en: 'Beginner', color: 'bg-green-100 text-green-800' },
  2: { fr: 'Intermédiaire', en: 'Intermediate', color: 'bg-blue-100 text-blue-800' },
  3: { fr: 'Avancé', en: 'Advanced', color: 'bg-purple-100 text-purple-800' },
  4: { fr: 'Expert', en: 'Expert', color: 'bg-red-100 text-red-800' },
};

export function AdminModuleCard({ module, onEdit }: AdminModuleCardProps) {
  const t = useTranslations('AdminSyllabus');
  const locale = useLocale() as 'fr' | 'en';
  const [audioState, setAudioState] = useState<AudioState>(null);
  const [generating, setGenerating] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);

  async function handleGenerateAudio() {
    setGenerating(true);
    try {
      const result = await generateModuleMedia(module.id, 'audio', locale);
      setAudioState({ status: result.status });
      setToast({ message: t('audioGenerateSuccess'), type: 'success' });
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setToast({ message: t('audioAlreadyExists'), type: 'error' });
      } else {
        setToast({ message: t('audioGenerateError'), type: 'error' });
      }
    } finally {
      setGenerating(false);
    }
  }

  const title = locale === 'fr' ? module.title_fr : module.title_en;
  const description = locale === 'fr' ? module.description_fr : module.description_en;
  const levelLabel = LEVEL_LABELS[module.level] ?? LEVEL_LABELS[1];

  return (
    <Card className="relative flex flex-col hover:shadow-md transition-shadow min-h-[200px]">
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={`absolute top-2 right-2 z-10 flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium shadow ${
            toast.type === 'success'
              ? 'bg-green-100 text-green-800'
              : 'bg-red-100 text-red-800'
          }`}
        >
          {toast.message}
        </div>
      )}
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-xs font-mono text-muted-foreground shrink-0">
              M{String(module.module_number).padStart(2, '0')}
            </span>
            <Badge
              className={`text-xs shrink-0 ${levelLabel.color}`}
              variant="outline"
            >
              {locale === 'fr' ? levelLabel.fr : levelLabel.en}
            </Badge>
            {module.bloom_level && (
              <Badge variant="secondary" className="text-xs shrink-0 capitalize">
                {module.bloom_level}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {audioState && audioState.status === 'ready' ? (
              <CheckCircle2 className="h-4 w-4 text-green-600" aria-label={t('audioStatus.ready')} />
            ) : audioState && (audioState.status === 'generating' || audioState.status === 'pending') ? (
              <Loader2 className="h-4 w-4 animate-spin text-blue-500" aria-label={t(`audioStatus.${audioState.status}`)} />
            ) : (
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={handleGenerateAudio}
                disabled={generating}
                aria-label={t('generateAudio')}
              >
                {generating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              onClick={() => onEdit(module)}
              aria-label={t('editModule')}
            >
              <Edit2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <CardTitle className="text-base leading-snug mt-1 line-clamp-2">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 flex-1">
        {description && (
          <p className="text-sm text-muted-foreground line-clamp-2">{description}</p>
        )}
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground mt-auto">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {module.estimated_hours}h
          </span>
          <span className="flex items-center gap-1">
            <Layers className="h-3 w-3" />
            {module.unit_count} {t('units')}
          </span>
          {module.source_references.length > 0 && (
            <span className="flex items-center gap-1">
              <BookOpen className="h-3 w-3" />
              {module.source_references.length} {t('sources')}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

interface NewModuleCardProps {
  onCreate: () => void;
}

export function NewModuleCard({ onCreate }: NewModuleCardProps) {
  const t = useTranslations('AdminSyllabus');
  return (
    <Card
      className="flex flex-col items-center justify-center min-h-[200px] border-dashed cursor-pointer hover:border-primary hover:bg-primary/5 transition-colors"
      onClick={onCreate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onCreate()}
    >
      <Plus className="h-8 w-8 text-muted-foreground mb-2" />
      <span className="text-sm text-muted-foreground">{t('createModule')}</span>
    </Card>
  );
}
