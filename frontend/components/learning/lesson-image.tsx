'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { X, Maximize2 } from 'lucide-react';
import { getLessonImageStatus, LessonImageStatus } from '@/lib/api';

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_DURATION_MS = 120000;

interface LessonImageProps {
  lessonId: string;
}

export function LessonImage({ lessonId }: LessonImageProps) {
  const t = useTranslations('LessonViewer');
  const [status, setStatus] = useState<LessonImageStatus>('pending');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [altText, setAltText] = useState<string>('');
  const [imageLoaded, setImageLoaded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimeRef = useRef<number>(0);
  const activeRef = useRef<boolean>(true);

  useEffect(() => {
    activeRef.current = true;
    startTimeRef.current = Date.now();

    const schedulePoll = () => {
      timerRef.current = setTimeout(async () => {
        if (!activeRef.current) return;

        if (Date.now() - startTimeRef.current > MAX_POLL_DURATION_MS) {
          setStatus('failed');
          return;
        }

        try {
          const data = await getLessonImageStatus(lessonId);
          if (!activeRef.current) return;

          setStatus(data.status);

          if (data.status === 'ready' && data.image_url) {
            setImageUrl(data.image_url);
            setAltText(data.alt_text ?? '');
          } else if (data.status !== 'failed') {
            schedulePoll();
          }
        } catch {
          if (activeRef.current) {
            schedulePoll();
          }
        }
      }, POLL_INTERVAL_MS);
    };

    schedulePoll();

    return () => {
      activeRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [lessonId]);

  if (status === 'failed') {
    return null;
  }

  if (status !== 'ready' || !imageUrl) {
    return (
      <div
        className="w-full rounded-lg overflow-hidden bg-gray-100 animate-pulse"
        role="status"
        aria-label={t('imagePending')}
      >
        <div className="w-full aspect-video flex items-center justify-center">
          <p className="text-sm text-gray-500 px-4 text-center">{t('imagePending')}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="w-full rounded-lg overflow-hidden relative">
        <div
          className={`transition-opacity duration-300 ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt={altText}
            loading="lazy"
            width={512}
            className="w-full max-w-[512px] mx-auto block rounded-lg"
            onLoad={() => setImageLoaded(true)}
          />
        </div>

        {!imageLoaded && (
          <div
            className="absolute inset-0 bg-gray-100 animate-pulse rounded-lg flex items-center justify-center"
            aria-hidden="true"
          >
            <p className="text-sm text-gray-500 px-4 text-center">{t('imagePending')}</p>
          </div>
        )}

        {imageLoaded && (
          <button
            type="button"
            onClick={() => setFullscreen(true)}
            className="absolute top-2 right-2 bg-black/40 text-white rounded-md p-1.5 min-h-11 min-w-11 flex items-center justify-center hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            aria-label={t('imageViewFullscreen')}
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {fullscreen && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={altText}
          onClick={() => setFullscreen(false)}
        >
          <button
            type="button"
            onClick={() => setFullscreen(false)}
            className="absolute top-4 right-4 bg-white/20 text-white rounded-md p-2 min-h-11 min-w-11 flex items-center justify-center hover:bg-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            aria-label={t('imageCloseFullscreen')}
          >
            <X className="w-5 h-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt={altText}
            className="max-w-full max-h-full object-contain rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
