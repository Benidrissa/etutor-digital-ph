'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { ChevronDown, ChevronUp, Download, Film } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { API_BASE } from '@/lib/api';

interface VideoSlide {
  slide_number: number;
  title: string;
  narration: string;
  key_points: string[];
}

interface VideoScript {
  title: string;
  estimated_duration_seconds: number;
  slides: VideoSlide[];
}

interface ModuleVideoPlayerProps {
  mediaId: string;
  moduleId: string;
  language: 'fr' | 'en';
  durationSeconds?: number;
  mimeType?: string;
}

export function ModuleVideoPlayer({
  mediaId,
  moduleId,
  language,
  durationSeconds,
  mimeType,
}: ModuleVideoPlayerProps) {
  const t = useTranslations('ModuleMedia');
  const videoRef = useRef<HTMLVideoElement>(null);
  const [script, setScript] = useState<VideoScript | null>(null);
  const [expandedSlide, setExpandedSlide] = useState<number | null>(0);
  const [loadError, setLoadError] = useState(false);

  const mediaUrl = `${API_BASE}/api/v1/modules/${moduleId}/media/${mediaId}/data`;
  const isVideoFile = mimeType && mimeType.startsWith('video/');
  const isJsonScript = mimeType === 'application/json';

  useEffect(() => {
    if (!isJsonScript) return;

    fetch(mediaUrl, {
      headers: { Accept: 'application/json' },
    })
      .then((r) => r.json())
      .then((data: VideoScript) => setScript(data))
      .catch(() => setLoadError(true));
  }, [mediaUrl, isJsonScript]);

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '';
    const mins = Math.floor(seconds / 60);
    return `${mins} min`;
  };

  if (isVideoFile) {
    return (
      <div className="rounded-xl border border-stone-200 bg-stone-50 overflow-hidden">
        <video
          ref={videoRef}
          src={mediaUrl}
          controls
          playsInline
          className="w-full max-h-64"
          aria-label={`${t('videoSummary')} ${language.toUpperCase()}`}
        >
          <track kind="captions" />
        </video>
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-xs text-stone-600">
            {t('videoSummary')} · {language.toUpperCase()}
            {durationSeconds ? ` · ${formatDuration(durationSeconds)}` : ''}
          </span>
          <a
            href={mediaUrl}
            download
            aria-label={t('download')}
            className="inline-flex items-center gap-1 text-xs text-stone-600 hover:text-stone-900"
          >
            <Download className="h-3 w-3" />
            {t('download')}
          </a>
        </div>
      </div>
    );
  }

  if (isJsonScript) {
    if (loadError) {
      return (
        <div className="rounded-xl border border-stone-200 bg-stone-50 p-4 text-sm text-stone-500">
          {t('videoScriptError')}
        </div>
      );
    }

    if (!script) {
      return (
        <div className="rounded-xl border border-stone-200 bg-stone-50 p-4 animate-pulse">
          <div className="h-4 bg-stone-200 rounded w-2/3 mb-2" />
          <div className="h-3 bg-stone-200 rounded w-1/2" />
        </div>
      );
    }

    return (
      <div className="rounded-xl border border-stone-200 bg-stone-50">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-stone-200">
          <Film className="h-4 w-4 text-stone-500 flex-shrink-0" />
          <span className="text-sm font-medium text-stone-700 flex-1 truncate">{script.title}</span>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Badge variant="secondary" className="text-xs">
              {language.toUpperCase()}
            </Badge>
            {script.estimated_duration_seconds && (
              <Badge variant="outline" className="text-xs">
                {formatDuration(script.estimated_duration_seconds)}
              </Badge>
            )}
          </div>
        </div>

        <div className="divide-y divide-stone-100">
          {script.slides.map((slide, index) => (
            <div key={slide.slide_number} className="px-4 py-3">
              <button
                className="flex w-full items-center justify-between text-left gap-2"
                onClick={() => setExpandedSlide(expandedSlide === index ? null : index)}
                aria-expanded={expandedSlide === index}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-teal-100 text-xs font-semibold text-teal-700">
                    {slide.slide_number}
                  </span>
                  <span className="text-sm font-medium text-stone-800 truncate">{slide.title}</span>
                </div>
                {expandedSlide === index ? (
                  <ChevronUp className="h-4 w-4 text-stone-400 flex-shrink-0" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-stone-400 flex-shrink-0" />
                )}
              </button>

              {expandedSlide === index && (
                <div className="mt-3 pl-8 space-y-3">
                  <p className="text-sm text-stone-700 leading-relaxed">{slide.narration}</p>
                  {slide.key_points.length > 0 && (
                    <ul className="space-y-1.5">
                      {slide.key_points.map((point, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-stone-600">
                          <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal-500" />
                          {point}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('videoSummary')}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-stone-500">{t('videoUnavailable')}</p>
      </CardContent>
    </Card>
  );
}
