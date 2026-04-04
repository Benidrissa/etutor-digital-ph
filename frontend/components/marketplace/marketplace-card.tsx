'use client';

import { useTranslations, useLocale } from 'next-intl';
import Link from 'next/link';
import { GraduationCap, Clock, BookOpen } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { type MarketplaceCourse } from '@/lib/api';
import { PriceBadge } from './price-badge';
import { StarRating } from './star-rating';

interface MarketplaceCardProps {
  course: MarketplaceCourse;
  locale: string;
}

export function MarketplaceCard({ course, locale }: MarketplaceCardProps) {
  const t = useTranslations('Marketplace');
  const tTax = useTranslations('Taxonomy');
  const tCourses = useTranslations('Courses');
  const currentLocale = useLocale();

  const title = currentLocale === 'fr' ? course.title_fr : course.title_en;
  const description =
    currentLocale === 'fr' ? course.description_fr : course.description_en;

  const firstDomain = course.course_domain[0];
  const firstLevel = course.course_level[0];

  return (
    <Card className="flex flex-col h-full border border-stone-200 hover:shadow-md transition-shadow duration-200">
      <div className="relative">
        {course.cover_image_url ? (
          <div className="relative h-40 overflow-hidden rounded-t-lg bg-teal-50">
            <img
              src={course.cover_image_url}
              alt={title}
              className="w-full h-full object-cover"
            />
          </div>
        ) : (
          <div className="h-40 rounded-t-lg bg-gradient-to-br from-teal-600 to-amber-500 flex items-center justify-center">
            <GraduationCap className="h-16 w-16 text-white opacity-80" aria-hidden="true" />
          </div>
        )}
        <div className="absolute top-2 right-2">
          <PriceBadge isFree={course.is_free} credits={course.price_credits} />
        </div>
      </div>

      <CardHeader className="pb-2">
        <div className="flex flex-wrap gap-1 mb-1">
          {firstDomain && (
            <span className="inline-block text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
              {tTax(`domains.${firstDomain}`)}
            </span>
          )}
          {firstLevel && (
            <span className="inline-block text-[10px] font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-full px-2 py-0.5">
              {tTax(`levels.${firstLevel}`)}
            </span>
          )}
        </div>

        <CardTitle className="text-base leading-tight text-stone-900 line-clamp-2">
          {title}
        </CardTitle>

        <div className="flex items-center gap-1.5 mt-1">
          {course.expert_avatar_url ? (
            <img
              src={course.expert_avatar_url}
              alt={course.expert_name}
              className="h-5 w-5 rounded-full object-cover"
              aria-hidden="true"
            />
          ) : (
            <div className="h-5 w-5 rounded-full bg-teal-100 flex items-center justify-center" aria-hidden="true">
              <span className="text-[8px] font-bold text-teal-700">
                {course.expert_name.charAt(0).toUpperCase()}
              </span>
            </div>
          )}
          <span className="text-xs text-stone-500">
            {t('by')} {course.expert_name}
          </span>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col flex-1 pt-0 gap-3">
        {description && (
          <p className="text-sm text-stone-600 line-clamp-2">{description}</p>
        )}

        <StarRating rating={course.rating} reviewCount={course.review_count} />

        <div className="flex items-center gap-4 text-xs text-stone-500">
          <div className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{tCourses('hours', { count: course.estimated_hours })}</span>
          </div>
          <div className="flex items-center gap-1">
            <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{tCourses('modules', { count: course.module_count })}</span>
          </div>
        </div>

        <div className="mt-auto pt-2">
          <Link
            href={`/${locale}/marketplace/${course.slug}`}
            className="flex items-center justify-center w-full rounded-md bg-teal-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-teal-700 transition-colors min-h-11"
            aria-label={`${t('viewCourse')}: ${title}`}
          >
            {t('viewCourse')}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
