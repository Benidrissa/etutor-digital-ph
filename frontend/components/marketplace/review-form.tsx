'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Star } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { submitCourseReview } from '@/lib/api';

interface ReviewFormProps {
  courseId: string;
  onSuccess: () => void;
}

export function ReviewForm({ courseId, onSuccess }: ReviewFormProps) {
  const t = useTranslations('Marketplace');
  const [rating, setRating] = useState(0);
  const [hovered, setHovered] = useState(0);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (rating === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitCourseReview({ course_id: courseId, rating, comment: comment || undefined });
      onSuccess();
    } catch {
      setError(t('reviewError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-stone-700">{t('yourRating')}</label>
        <div className="flex items-center gap-1" role="group" aria-label={t('yourRating')}>
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              onClick={() => setRating(star)}
              onMouseEnter={() => setHovered(star)}
              onMouseLeave={() => setHovered(0)}
              className="min-h-11 min-w-11 flex items-center justify-center rounded-md hover:bg-stone-50 transition-colors"
              aria-label={t(`stars.${star}` as Parameters<typeof t>[0])}
            >
              <Star
                className={`h-6 w-6 transition-colors ${
                  star <= (hovered || rating)
                    ? 'text-amber-400 fill-amber-400'
                    : 'text-stone-300'
                }`}
                aria-hidden="true"
              />
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="review-comment" className="text-sm font-medium text-stone-700">
          {t('comment')}
        </label>
        <Textarea
          id="review-comment"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t('commentPlaceholder')}
          rows={3}
          className="resize-none text-base"
          maxLength={500}
        />
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">{error}</p>
      )}

      <Button
        type="submit"
        disabled={rating === 0 || submitting}
        className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
      >
        {submitting ? t('submittingReview') : t('submitReview')}
      </Button>
    </form>
  );
}
