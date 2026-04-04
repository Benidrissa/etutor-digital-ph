'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import {
  GraduationCap,
  Clock,
  BookOpen,
  Star,
  ChevronLeft,
  CheckCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ExpertBio } from './expert-bio';
import { PurchaseDialog } from './purchase-dialog';
import { ReviewCard } from './review-card';
import { ReviewForm } from './review-form';
import {
  getCourseReviews,
  type CourseDetailResponse,
  type CourseReview,
} from '@/lib/api';

const LEVEL_COLORS: Record<string, string> = {
  beginner: 'bg-green-50 text-green-700 border-green-200',
  intermediate: 'bg-blue-50 text-blue-700 border-blue-200',
  advanced: 'bg-amber-50 text-amber-700 border-amber-200',
  expert: 'bg-red-50 text-red-700 border-red-200',
};

function StarRatingDisplay({ rating, count }: { rating: number; count: number }) {
  const t = useTranslations('Marketplace');
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex items-center gap-0.5" aria-label={`${rating.toFixed(1)} out of 5 stars`}>
        {[1, 2, 3, 4, 5].map((star) => (
          <Star
            key={star}
            className={`h-4 w-4 ${
              star <= Math.round(rating)
                ? 'text-amber-400 fill-amber-400'
                : 'text-stone-300'
            }`}
            aria-hidden="true"
          />
        ))}
      </div>
      <span className="text-sm font-semibold text-stone-700">{rating.toFixed(1)}</span>
      <span className="text-sm text-stone-400">({t('reviewCount', { count })})</span>
    </div>
  );
}

interface CourseDetailProps {
  course: CourseDetailResponse;
}

export function CourseDetail({ course }: CourseDetailProps) {
  const t = useTranslations('Marketplace');
  const tTax = useTranslations('Taxonomy');
  const locale = useLocale() as 'en' | 'fr';
  const router = useRouter();

  const [isEnrolled, setIsEnrolled] = useState(course.enrolled);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reviews, setReviews] = useState<CourseReview[]>([]);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewPage, setReviewPage] = useState(1);
  const [loadingReviews, setLoadingReviews] = useState(true);
  const [showReviewForm, setShowReviewForm] = useState(false);

  const title = locale === 'fr' ? course.title_fr : course.title_en;
  const description = locale === 'fr' ? course.description_fr : course.description_en;

  useEffect(() => {
    let cancelled = false;
    getCourseReviews(course.id, 1, 10)
      .then((data) => {
        if (!cancelled) {
          setReviews(data.reviews);
          setReviewTotal(data.total);
          setLoadingReviews(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoadingReviews(false);
      });
    return () => { cancelled = true; };
  }, [course.id]);

  const handleLoadMoreReviews = () => {
    const nextPage = reviewPage + 1;
    getCourseReviews(course.id, nextPage, 10)
      .then((data) => {
        setReviews((prev) => [...prev, ...data.reviews]);
        setReviewPage(nextPage);
      })
      .catch(() => {});
  };

  const handleEnrollSuccess = () => {
    setIsEnrolled(true);
  };

  const handleViewCourse = () => {
    router.push('/modules');
  };

  const hasMoreReviews = reviews.length < reviewTotal;

  return (
    <div className="container mx-auto max-w-3xl px-4 py-6 flex flex-col gap-6">
      {/* Back link */}
      <button
        type="button"
        onClick={() => router.push('/courses')}
        className="flex items-center gap-1.5 text-sm text-teal-600 hover:text-teal-700 font-medium self-start min-h-11"
        aria-label={t('backToCatalog')}
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        {t('backToCatalog')}
      </button>

      {/* Cover image */}
      {course.cover_image_url ? (
        <div className="relative h-52 sm:h-64 rounded-xl overflow-hidden bg-teal-50">
          <img
            src={course.cover_image_url}
            alt={title}
            className="w-full h-full object-cover"
          />
        </div>
      ) : (
        <div className="h-52 sm:h-64 rounded-xl bg-gradient-to-br from-teal-600 to-amber-500 flex items-center justify-center">
          <GraduationCap className="h-20 w-20 text-white opacity-80" aria-hidden="true" />
        </div>
      )}

      {/* Title and meta */}
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-bold text-stone-900 leading-tight">{title}</h1>

        {/* Taxonomy badges */}
        <div className="flex flex-wrap gap-1.5">
          {course.course_domain?.map((d) => (
            <span
              key={d}
              className="inline-block text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1"
            >
              {tTax(`domains.${d}`)}
            </span>
          ))}
          {course.course_level?.map((l) => (
            <span
              key={l}
              className={`inline-block text-xs font-medium border rounded-full px-2.5 py-1 ${
                LEVEL_COLORS[l] || 'bg-stone-50 text-stone-700 border-stone-200'
              }`}
            >
              {tTax(`levels.${l}`)}
            </span>
          ))}
          {course.audience_type?.map((a) => (
            <span
              key={a}
              className="inline-block text-xs font-medium text-violet-700 bg-violet-50 border border-violet-200 rounded-full px-2.5 py-1"
            >
              {tTax(`audience_types.${a}`)}
            </span>
          ))}
        </div>

        {/* Stats row */}
        <div className="flex flex-wrap items-center gap-4 text-sm text-stone-500">
          <div className="flex items-center gap-1">
            <Clock className="h-4 w-4" aria-hidden="true" />
            <span>{t('hours', { count: course.estimated_hours })}</span>
          </div>
          <div className="flex items-center gap-1">
            <BookOpen className="h-4 w-4" aria-hidden="true" />
            <span>{t('modules', { count: course.module_count })}</span>
          </div>
          {course.review_count > 0 && (
            <StarRatingDisplay rating={course.average_rating} count={course.review_count} />
          )}
        </div>

        {/* Price and CTA */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
          <div className="text-xl font-bold text-stone-900">
            {course.is_free ? (
              <span className="text-teal-600">{t('free')}</span>
            ) : (
              <span>{t('credits', { count: course.price_credits })}</span>
            )}
          </div>

          {isEnrolled ? (
            <Button
              className="min-h-11 bg-teal-600 hover:bg-teal-700 sm:ml-auto"
              onClick={handleViewCourse}
            >
              <CheckCircle className="h-4 w-4 mr-2" aria-hidden="true" />
              {t('viewCourse')}
            </Button>
          ) : (
            <Button
              className="min-h-11 bg-teal-600 hover:bg-teal-700 sm:ml-auto"
              onClick={() => setDialogOpen(true)}
            >
              {course.is_free
                ? t('enrollFree')
                : t('purchase', { price: course.price_credits })}
            </Button>
          )}
        </div>
      </div>

      {/* Description */}
      {description && (
        <div className="flex flex-col gap-1">
          <p className="text-stone-700 leading-relaxed">{description}</p>
        </div>
      )}

      {/* Modules preview */}
      {course.modules_preview.length > 0 && (
        <Card className="border border-stone-200">
          <CardContent className="p-4 flex flex-col gap-0">
            <h2 className="text-base font-semibold text-stone-900 mb-3">
              {t('modulesPreview')}
            </h2>
            <ul className="flex flex-col gap-0">
              {course.modules_preview
                .sort((a, b) => a.order_index - b.order_index)
                .map((mod, idx) => {
                  const modTitle = locale === 'fr' ? mod.title_fr : mod.title_en;
                  return (
                    <li
                      key={mod.id}
                      className="flex items-center gap-3 py-2.5 border-b border-stone-100 last:border-0"
                    >
                      <span className="shrink-0 h-6 w-6 rounded-full bg-teal-50 text-teal-700 text-xs font-semibold flex items-center justify-center">
                        {idx + 1}
                      </span>
                      <span className="text-sm text-stone-700 leading-snug">{modTitle}</span>
                    </li>
                  );
                })}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Expert bio */}
      {course.expert && (
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-stone-900">{t('expertBio')}</h2>
          <ExpertBio expert={course.expert} />
        </div>
      )}

      {/* Reviews section */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-stone-900">{t('reviews')}</h2>
          {course.review_count > 0 && (
            <StarRatingDisplay rating={course.average_rating} count={course.review_count} />
          )}
        </div>

        {loadingReviews ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-16 bg-stone-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : reviews.length === 0 ? (
          <p className="text-sm text-stone-500 py-4">{t('noReviews')}</p>
        ) : (
          <div className="flex flex-col">
            {reviews.map((review) => (
              <ReviewCard key={review.id} review={review} />
            ))}
          </div>
        )}

        {hasMoreReviews && (
          <button
            type="button"
            className="text-sm text-teal-600 hover:text-teal-700 font-medium self-start min-h-11"
            onClick={handleLoadMoreReviews}
          >
            {t('loadMoreReviews')}
          </button>
        )}

        {/* Review form — shown only for enrolled learners */}
        {isEnrolled && (
          <div className="border-t border-stone-100 pt-4">
            {showReviewForm ? (
              <div className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold text-stone-900">{t('leaveReview')}</h3>
                <ReviewForm
                  courseId={course.id}
                  onSuccess={() => {
                    setShowReviewForm(false);
                    getCourseReviews(course.id, 1, 10).then((data) => {
                      setReviews(data.reviews);
                      setReviewTotal(data.total);
                    }).catch(() => {});
                  }}
                />
              </div>
            ) : (
              <Button
                variant="outline"
                className="min-h-11"
                onClick={() => setShowReviewForm(true)}
              >
                {t('leaveReview')}
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Purchase dialog */}
      <PurchaseDialog
        course={course}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSuccess={handleEnrollSuccess}
      />
    </div>
  );
}
