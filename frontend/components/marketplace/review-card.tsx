'use client';

import { Star } from 'lucide-react';
import type { CourseReview } from '@/lib/api';

interface ReviewCardProps {
  review: CourseReview;
}

function StarRating({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Star
          key={star}
          className={`h-4 w-4 ${
            star <= rating ? 'text-amber-400 fill-amber-400' : 'text-stone-300'
          }`}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

export function ReviewCard({ review }: ReviewCardProps) {
  const date = new Date(review.created_at).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });

  return (
    <div className="flex flex-col gap-2 py-4 border-b border-stone-100 last:border-0">
      <div className="flex items-center gap-3">
        {review.user_avatar_url ? (
          <img
            src={review.user_avatar_url}
            alt={review.user_name}
            className="h-8 w-8 rounded-full object-cover shrink-0"
          />
        ) : (
          <div className="h-8 w-8 rounded-full bg-teal-100 flex items-center justify-center shrink-0">
            <span className="text-xs font-semibold text-teal-700">
              {review.user_name.charAt(0).toUpperCase()}
            </span>
          </div>
        )}
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-sm font-medium text-stone-900 truncate">{review.user_name}</span>
          <div className="flex items-center gap-2">
            <StarRating rating={review.rating} />
            <span className="text-xs text-stone-400">{date}</span>
          </div>
        </div>
      </div>
      {review.comment && (
        <p className="text-sm text-stone-600 leading-relaxed pl-11">{review.comment}</p>
      )}
    </div>
  );
}
