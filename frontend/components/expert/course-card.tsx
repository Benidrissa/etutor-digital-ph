'use client';

import Link from 'next/link';
import { useTranslations, useLocale } from 'next-intl';
import { MoreVertical, Globe, GlobeLock, Trash2, Pencil, BookOpen } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';

export interface ExpertCourse {
  id: string;
  title_fr: string;
  title_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  estimated_hours: number;
  cover_image_url: string | null;
  status: 'draft' | 'published' | 'archived';
  created_at: string;
  updated_at: string;
  module_count?: number;
  price_credits?: number;
}

interface CourseCardProps {
  course: ExpertCourse;
  onPublish: (course: ExpertCourse) => void;
  onUnpublish: (course: ExpertCourse) => void;
  onDelete: (course: ExpertCourse) => void;
}

export function ExpertCourseCard({
  course,
  onPublish,
  onUnpublish,
  onDelete,
}: CourseCardProps) {
  const t = useTranslations('ExpertCourses');
  const locale = useLocale();

  const title = locale === 'fr' ? course.title_fr : course.title_en;

  const statusVariant =
    course.status === 'published'
      ? 'default'
      : course.status === 'archived'
        ? 'secondary'
        : 'outline';

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/${locale}/expert/courses/${course.id}`}
          className="flex flex-col gap-1 text-left min-w-0 flex-1"
          aria-label={title}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{title}</span>
            <Badge variant={statusVariant}>{t(`status.${course.status}`)}</Badge>
          </div>
          {(course.course_domain?.length > 0 || course.course_level?.length > 0) && (
            <div className="flex gap-1 flex-wrap">
              {course.course_domain?.map((d) => (
                <span
                  key={d}
                  className="text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-1.5 py-0.5"
                >
                  {d.replace(/_/g, ' ')}
                </span>
              ))}
              {course.course_level?.map((l) => (
                <span
                  key={l}
                  className="text-[10px] font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-full px-1.5 py-0.5"
                >
                  {l}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <span className="text-xs text-muted-foreground">
              {t('estimatedHours', { hours: course.estimated_hours })}
            </span>
            {course.module_count !== undefined && (
              <span className="text-xs text-muted-foreground">
                {t('moduleCount', { count: course.module_count })}
              </span>
            )}
            {course.price_credits !== undefined && (
              <span className="text-xs text-muted-foreground">
                {course.price_credits === 0 ? t('priceFree') : `${course.price_credits} crédits`}
              </span>
            )}
          </div>
        </Link>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 min-h-11 hidden sm:flex"
            asChild
          >
            <Link href={`/${locale}/expert/courses/${course.id}`}>
              <Pencil className="h-4 w-4" aria-hidden="true" />
              <span className="hidden md:inline">{t('edit')}</span>
            </Link>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="sm"
                  className="min-h-11 min-w-11 p-2 shrink-0"
                  aria-label={t('actions')}
                />
              }
            >
              <MoreVertical className="h-4 w-4" aria-hidden="true" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link href={`/${locale}/expert/courses/${course.id}`} className="sm:hidden">
                  <BookOpen className="mr-2 h-4 w-4" />
                  {t('edit')}
                </Link>
              </DropdownMenuItem>
              {course.status !== 'published' && (
                <DropdownMenuItem onClick={() => onPublish(course)}>
                  <Globe className="mr-2 h-4 w-4" />
                  {t('publish')}
                </DropdownMenuItem>
              )}
              {course.status === 'published' && (
                <DropdownMenuItem onClick={() => onUnpublish(course)}>
                  <GlobeLock className="mr-2 h-4 w-4" />
                  {t('unpublish')}
                </DropdownMenuItem>
              )}
              {course.status === 'draft' && (
                <DropdownMenuItem
                  onClick={() => onDelete(course)}
                  className="text-destructive"
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t('delete')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </Card>
  );
}
