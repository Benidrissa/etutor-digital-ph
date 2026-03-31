'use client';

import { cn } from '@/lib/utils';

interface ChatSkeletonProps {
  className?: string;
}

export function ChatSkeleton({ className }: ChatSkeletonProps) {
  return (
    <div className={cn('space-y-4 p-4', className)}>
      {/* Skeleton for user message */}
      <div className="flex w-full justify-end">
        <div className="max-w-[85%] sm:max-w-[75%] ml-4">
          <div className="h-12 bg-primary/20 rounded-lg animate-pulse" />
        </div>
      </div>

      {/* Skeleton for AI response */}
      <div className="flex w-full justify-start">
        <div className="max-w-[85%] sm:max-w-[75%] mr-4 space-y-2">
          <div className="h-16 bg-muted animate-pulse rounded-lg" />
          <div className="h-8 bg-muted animate-pulse rounded-lg w-3/4" />
          {/* Source skeleton */}
          <div className="flex gap-2 mt-2">
            <div className="h-6 w-20 bg-muted/60 animate-pulse rounded-md" />
            <div className="h-6 w-24 bg-muted/60 animate-pulse rounded-md" />
          </div>
        </div>
      </div>

      {/* Another user message skeleton */}
      <div className="flex w-full justify-end">
        <div className="max-w-[85%] sm:max-w-[75%] ml-4">
          <div className="h-8 bg-primary/20 rounded-lg animate-pulse" />
        </div>
      </div>
    </div>
  );
}