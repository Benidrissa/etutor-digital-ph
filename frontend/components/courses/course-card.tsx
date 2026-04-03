'use client';

import { useTranslations, useLocale } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Clock, BookOpen } from 'lucide-react';

export interface CourseData {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  domain: string | null;
  estimated_hours: number;
  module_count: number;
  status: string;
}

interface CourseCardProps {
  course: CourseData;
  isEnrolled?: boolean;
  onEnroll?: (courseId: string) => void;
  enrolling?: boolean;
}

export function CourseCard({ course, isEnrolled, onEnroll, enrolling }: CourseCardProps) {
  const t = useTranslations('Courses');
  const locale = useLocale() as 'fr' | 'en';

  const title = locale === 'fr' ? course.title_fr : course.title_en;
  const description = locale === 'fr' ? course.description_fr : course.description_en;

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-3">
        {course.domain && (
          <Badge variant="secondary" className="w-fit mb-2 text-xs">
            {course.domain}
          </Badge>
        )}
        <CardTitle className="text-base leading-tight">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 gap-3 pt-0">
        {description && (
          <p className="text-sm text-muted-foreground line-clamp-3">{description}</p>
        )}
        <div className="flex items-center gap-4 text-xs text-muted-foreground mt-auto">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {t('estimatedHours', { hours: course.estimated_hours })}
          </span>
          {course.module_count > 0 && (
            <span className="flex items-center gap-1">
              <BookOpen className="h-3 w-3" />
              {t('modules', { count: course.module_count })}
            </span>
          )}
        </div>
        <Button
          size="sm"
          className="w-full min-h-11"
          variant={isEnrolled ? 'secondary' : 'default'}
          disabled={isEnrolled || enrolling}
          onClick={() => !isEnrolled && onEnroll?.(course.id)}
        >
          {isEnrolled ? t('enrolled') : t('enroll')}
        </Button>
      </CardContent>
    </Card>
  );
}
