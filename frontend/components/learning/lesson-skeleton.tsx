'use client';

import { Card, CardContent } from '@/components/ui/card';

export function LessonSkeleton() {
  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      {/* Breadcrumb skeleton */}
      <div className="mb-6">
        <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
      </div>

      {/* Header skeleton */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className="h-6 w-16 bg-gray-200 rounded animate-pulse" />
          <div className="h-4 w-20 bg-gray-200 rounded animate-pulse" />
        </div>
        <div className="h-8 w-3/4 bg-gray-200 rounded animate-pulse mb-3" />
        <div className="h-6 w-full bg-gray-200 rounded animate-pulse mb-2" />
        <div className="h-6 w-2/3 bg-gray-200 rounded animate-pulse" />
      </div>

      {/* Content skeleton */}
      <Card>
        <CardContent className="p-6">
          {/* Introduction skeleton */}
          <div className="mb-6">
            <div className="h-6 w-24 bg-gray-200 rounded animate-pulse mb-3" />
            <div className="space-y-2">
              <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
              <div className="h-4 w-5/6 bg-gray-200 rounded animate-pulse" />
            </div>
          </div>

          {/* Main content skeleton */}
          <div className="space-y-6">
            {/* Section 1 */}
            <div>
              <div className="h-6 w-48 bg-gray-200 rounded animate-pulse mb-3" />
              <div className="space-y-3">
                <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-3/4 bg-gray-200 rounded animate-pulse" />
              </div>
            </div>

            {/* Section 2 */}
            <div>
              <div className="h-6 w-56 bg-gray-200 rounded animate-pulse mb-3" />
              <div className="space-y-3">
                <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-5/6 bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-2/3 bg-gray-200 rounded animate-pulse" />
              </div>
            </div>

            {/* West African example skeleton */}
            <div className="bg-teal-50 p-4 rounded-lg">
              <div className="h-5 w-40 bg-gray-200 rounded animate-pulse mb-2" />
              <div className="space-y-2">
                <div className="h-4 w-full bg-gray-200 rounded animate-pulse" />
                <div className="h-4 w-4/5 bg-gray-200 rounded animate-pulse" />
              </div>
            </div>

            {/* Key points skeleton */}
            <div>
              <div className="h-6 w-36 bg-gray-200 rounded animate-pulse mb-3" />
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-gray-200 rounded-full animate-pulse mt-2 flex-shrink-0" />
                    <div className="h-4 w-5/6 bg-gray-200 rounded animate-pulse" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Sources skeleton */}
      <div className="mt-6">
        <div className="h-5 w-28 bg-gray-200 rounded animate-pulse mb-3" />
        <div className="space-y-1">
          <div className="h-4 w-48 bg-gray-200 rounded animate-pulse" />
          <div className="h-4 w-52 bg-gray-200 rounded animate-pulse" />
        </div>
      </div>

      {/* Action button skeleton */}
      <div className="mt-8 text-center">
        <div className="h-11 w-48 bg-gray-200 rounded animate-pulse mx-auto" />
      </div>
    </div>
  );
}