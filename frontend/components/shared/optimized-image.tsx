'use client';

import Image from 'next/image';
import { useState } from 'react';
import { cn } from '@/lib/utils';

interface OptimizedImageProps {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
  priority?: boolean;
  sizes?: string;
  onLoad?: () => void;
}

interface OptimizedImageFillProps {
  src: string;
  alt: string;
  fill: true;
  className?: string;
  priority?: boolean;
  sizes?: string;
  onLoad?: () => void;
}

type Props = OptimizedImageProps | OptimizedImageFillProps;

export function OptimizedImage({ src, alt, priority = false, className, sizes, onLoad, ...rest }: Props) {
  const [loaded, setLoaded] = useState(false);

  const handleLoad = () => {
    setLoaded(true);
    onLoad?.();
  };

  if ('fill' in rest && rest.fill) {
    return (
      <Image
        src={src}
        alt={alt}
        fill
        priority={priority}
        loading={priority ? 'eager' : 'lazy'}
        sizes={sizes ?? '100vw'}
        className={cn('transition-opacity duration-300', loaded ? 'opacity-100' : 'opacity-0', className)}
        onLoad={handleLoad}
      />
    );
  }

  const { width, height } = rest as OptimizedImageProps;

  return (
    <Image
      src={src}
      alt={alt}
      width={width}
      height={height}
      priority={priority}
      loading={priority ? 'eager' : 'lazy'}
      sizes={sizes ?? `(max-width: 640px) 100vw, ${width}px`}
      className={cn('transition-opacity duration-300', loaded ? 'opacity-100' : 'opacity-0', className)}
      onLoad={handleLoad}
    />
  );
}
