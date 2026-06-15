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
  const [title, setTitle] = useState<string>('');
  const [labels, setLabels] = useState<string[]>([]);
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
          setTitle(data.title ?? '');
          setLabels(data.labels ?? []);
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
        className="w-full my-6 rounded-lg overflow-hidden animate-pulse"
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
      <figure className="w-full my-6">
        <button
          type="button"
          className="relative block w-full rounded-lg overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 min-h-11"
          aria-label={t('imageViewFullscreen')}
          onClick={() => setIsFullscreen(true)}
        >
          <Image
            src={imageUrl}
            alt={altText}
            width={1536}
            height={1024}
            loading="lazy"
            sizes="(max-width: 768px) 100vw, (max-width: 1024px) 90vw, 832px"
            unoptimized
            className={`w-full h-auto rounded-lg transition-opacity duration-300 ${
              isVisible ? 'opacity-100' : 'opacity-0'
            }`}
          />
          {title && (
            <span className="absolute inset-x-0 top-0 bg-gradient-to-b from-black/70 to-transparent px-4 pt-3 pb-8 text-left">
              <span className="block text-white font-semibold text-base sm:text-lg leading-snug drop-shadow">
                {title}
              </span>
            </span>
          )}
        </button>

        {labels.length > 0 && (
          <figcaption className="mt-2 flex flex-wrap gap-1.5">
            {labels.map((label, i) => (
              <span
                key={`${label}-${i}`}
                className="inline-block rounded-full bg-teal-50 text-teal-800 px-2.5 py-0.5 text-xs font-medium"
              >
                {label}
              </span>
            ))}
          </figcaption>
        )}
      </figure>

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
          <figure
            className="relative max-w-full max-h-full"
            onClick={(e) => e.stopPropagation()}
          >
            <Image
              src={imageUrl}
              alt={altText}
              width={1536}
              height={1024}
              sizes="(max-width: 640px) 100vw, 1024px"
              unoptimized
              className="max-w-full max-h-[85vh] w-auto h-auto object-contain rounded-lg"
            />
            {title && (
              <figcaption className="absolute inset-x-0 top-0 bg-gradient-to-b from-black/70 to-transparent px-4 pt-3 pb-8 text-white font-semibold text-lg leading-snug rounded-t-lg">
                {title}
              </figcaption>
            )}
          </figure>
        </div>
      )}
    </>
  );
}
