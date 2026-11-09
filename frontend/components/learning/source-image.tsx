'use client';

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { X } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import type { SourceImageMeta } from '@/lib/api';

interface SourceImageProps extends SourceImageMeta {
  language: 'fr' | 'en';
  /**
   * The picture could not be loaded (a missing binary answers 404). The
   * figure then takes no room at all, instead of an empty bordered box, and
   * the host can show something else.
   */
  onError?: () => void;
}

export function SourceImage({
  id,
  figure_number,
  caption: captionFallback,
  caption_fr,
  caption_en,
  attribution,
  alt_text_fr,
  alt_text_en,
  language,
  onError,
}: SourceImageProps) {
  const imageUrl = `${API_BASE}/api/v1/source-images/${id}/data?lang=${language}`;
  const t = useTranslations('SourceImage');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [failed, setFailed] = useState(false);

  // Esc closes the full-screen view.
  useEffect(() => {
    if (!isFullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setIsFullscreen(false);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [isFullscreen]);

  const caption = (language === 'fr' ? caption_fr : caption_en) ?? captionFallback;
  const altText = language === 'fr'
    ? (alt_text_fr ?? caption_fr ?? captionFallback ?? t('defaultAlt'))
    : (alt_text_en ?? caption_en ?? captionFallback ?? t('defaultAlt'));

  // Strip any leading figure-word already baked into figure_number (extraction
  // stores mixed formats: "1.3", "Figure 1.3", "Fig. 2-8", "Schéma 3"), then
  // prefix the localized label — restores the "Figure N" tag dropped in #844
  // without re-introducing the double-prefix it fixed.
  const bareNumber = figure_number
    ?.replace(/^(figures?|fig\.?|schémas?|tableaux?|graphiques?|diagrammes?|encadrés?|illustrations?)\s*/i, '')
    .trim();
  const figureLabel = bareNumber
    ? `${t('figure')} ${bareNumber}${caption ? ` — ${caption}` : ''}`
    : caption ?? '';

  if (failed) return null;

  const fail = () => {
    setFailed(true);
    setIsFullscreen(false);
    onError?.();
  };

  // Portalled to the body: a host's stacking context (the story stage keeps
  // its panels in one) must not put the viewer under the app's header or nav.
  const viewer = isFullscreen ? (
    <div
      className="fixed inset-0 z-[80] bg-black/90 flex flex-col items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={altText}
      onClick={() => setIsFullscreen(false)}
    >
      <button
        type="button"
        className="absolute top-4 right-4 min-h-11 min-w-11 flex items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
        aria-label={t('closeFullscreen')}
        autoFocus
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
        width={1920}
        height={1080}
        sizes="100vw"
        unoptimized
        className="max-w-full max-h-[80vh] w-auto h-auto object-contain rounded-lg"
        onClick={(e) => e.stopPropagation()}
        onError={fail}
        priority
      />

      {figureLabel || attribution ? (
        <div className="mt-4 text-center space-y-1 max-w-xl" onClick={(e) => e.stopPropagation()}>
          {figureLabel ? <p className="text-sm text-white/90">{figureLabel}</p> : null}
          {attribution ? <p className="text-xs text-white/70">{attribution}</p> : null}
        </div>
      ) : null}
    </div>
  ) : null;

  return (
    <>
      <figure className="my-6 w-full">
        <button
          type="button"
          className="w-full rounded-lg overflow-hidden border border-stone-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 min-h-11"
          aria-label={t('viewFullscreen')}
          onClick={() => setIsFullscreen(true)}
        >
          <Image
            src={imageUrl}
            alt={altText}
            // Bypass Next's image optimizer: upstream widths are arbitrary
            // (SVG re-derives, scanned PDF crops, etc.), so Next can't build
            // a safe srcset from deviceSizes — 1024 isn't in the ladder and
            // /_next/image returns 400, leaving the tile blank. The backend
            // /data endpoint already serves immutable webp/svg with a
            // year-long Cache-Control. Mirrors the fix in lesson-image.tsx
            // from #1616 and #1857.
            width={1024}
            height={768}
            sizes="(max-width: 768px) 100vw, (max-width: 1024px) 90vw, 832px"
            loading="lazy"
            unoptimized
            className={`w-full h-auto object-contain rounded-lg transition-opacity duration-300 ${
              isVisible ? 'opacity-100' : 'opacity-0'
            }`}
            onLoad={() => setIsVisible(true)}
            onError={fail}
          />
        </button>

        {figureLabel || attribution ? (
          <figcaption className="mt-2 px-1 space-y-1">
            {figureLabel ? <p className="text-sm text-stone-700 text-center">{figureLabel}</p> : null}
            {attribution ? (
              <p className="text-xs text-stone-500 text-center">{attribution}</p>
            ) : null}
          </figcaption>
        ) : null}
      </figure>

      {viewer && typeof document !== 'undefined' ? createPortal(viewer, document.body) : viewer}
    </>
  );
}
