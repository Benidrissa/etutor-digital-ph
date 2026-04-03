'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { X } from 'lucide-react';
import Image from 'next/image';
import { getLessonImageStatus, API_BASE } from '@/lib/api';
import type { LessonImageStatus } from '@/lib/api';

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 40;

interface LessonImageProps {
  lessonId: string;
  language: 'fr' | 'en';
}

export function LessonImage({ lessonId, language }: LessonImageProps) {
  const t = useTranslations('LessonImage');
  const [status, setStatus] = useState<LessonImageStatus>('pending');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [altText, setAltText] = useState<string>('');
  const [isVisible, setIsVisible] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const poll = useCallback(async () => {
    let attempts = 0;

    const tick = async () => {
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setStatus('failed');
        return;
      }
      attempts++;

      try {
        const data = await getLessonImageStatus(lessonId);
        setStatus(data.status);

        if (data.status === 'ready' && data.url) {
          const alt =
            language === 'fr'
              ? (data.alt_text_fr ?? data.alt_text ?? '')
              : (data.alt_text_en ?? data.alt_text ?? '');
          setAltText(alt);
          const resolvedUrl = data.url.startsWith('/')
            ? `${API_BASE}${data.url}`
            : data.url;
          setImageUrl(resolvedUrl);
          setTimeout(() => setIsVisible(true), 50);
          return;
        }

        if (data.status === 'failed') {
          return;
        }

        setTimeout(tick, POLL_INTERVAL_MS);
      } catch {
        setTimeout(tick, POLL_INTERVAL_MS);
      }
    };

    tick();
  }, [lessonId, language]);

  useEffect(() => {
    poll();
  }, [poll]);

  if (status === 'failed') {
    return null;
  }

  if (status !== 'ready' || !imageUrl) {
    return (
      <div
        className="w-full max-w-[512px] mx-auto my-6 rounded-lg overflow-hidden animate-pulse"
        aria-busy="true"
        aria-label={t('imagePending')}
      >
        <div className="bg-gray-200 h-48 flex items-center justify-center rounded-lg">
          <p className="text-gray-500 text-sm text-center px-4">{t('imagePending')}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="w-full max-w-[512px] mx-auto my-6">
        <button
          type="button"
          className="w-full rounded-lg overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 min-h-11"
          aria-label={t('imageViewFullscreen')}
          onClick={() => setIsFullscreen(true)}
        >
          <Image
            src={imageUrl}
            alt={altText}
            width={512}
            height={512}
            loading="lazy"
            sizes="(max-width: 640px) 100vw, 512px"
            className={`w-full h-auto object-cover rounded-lg transition-opacity duration-300 ${
              isVisible ? 'opacity-100' : 'opacity-0'
            }`}
          />
        </button>
      </div>

      {isFullscreen && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={altText}
          onClick={() => setIsFullscreen(false)}
        >
          <button
            type="button"
            className="absolute top-4 right-4 min-h-11 min-w-11 flex items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            aria-label={t('imageCloseFullscreen')}
            onClick={(e) => {
              e.stopPropagation();
              setIsFullscreen(false);
            }}
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
          <Image
            src={imageUrl}
            alt={altText}
            width={512}
            height={512}
            sizes="(max-width: 640px) 100vw, 512px"
            className="max-w-full max-h-full object-contain rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
