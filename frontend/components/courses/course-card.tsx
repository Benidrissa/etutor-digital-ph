"use client";

import { useTranslations, useLocale } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Clock, BookOpen, CheckCircle } from "lucide-react";

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
  cover_image_url: string | null;
}

interface CourseCardProps {
  course: CourseData;
  isEnrolled?: boolean;
  onEnroll?: (courseId: string) => void;
  enrolling?: boolean;
}

export function CourseCard({ course, isEnrolled, onEnroll, enrolling }: CourseCardProps) {
  const t = useTranslations("Courses");
  const locale = useLocale() as "fr" | "en";

  const title = locale === "fr" ? course.title_fr : course.title_en;
  const description =
    (locale === "fr" ? course.description_fr : course.description_en) ?? "";

  return (
    <Card className="flex flex-col h-full border border-stone-200 hover:shadow-md transition-shadow duration-200">
      {course.cover_image_url && (
        <div className="h-40 bg-teal-50 rounded-t-lg overflow-hidden">
          <img
            src={course.cover_image_url}
            alt={title}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      {!course.cover_image_url && (
        <div className="h-32 bg-gradient-to-br from-teal-500 to-teal-700 rounded-t-lg flex items-center justify-center">
          <BookOpen className="h-12 w-12 text-white opacity-60" />
        </div>
      )}
      <CardHeader className="pb-2">
        {course.domain && (
          <Badge variant="secondary" className="w-fit text-xs mb-1">
            {course.domain}
          </Badge>
        )}
        <CardTitle className="text-base leading-tight line-clamp-2">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 gap-3 pt-0">
        {description && (
          <p className="text-sm text-stone-600 line-clamp-3 flex-1">{description}</p>
        )}
        <div className="flex items-center gap-4 text-xs text-stone-500">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {t("hours", { count: course.estimated_hours })}
          </span>
          {course.module_count > 0 && (
            <span className="flex items-center gap-1">
              <BookOpen className="h-3 w-3" />
              {t("modules", { count: course.module_count })}
            </span>
          )}
        </div>
        {onEnroll && (
          <Button
            size="sm"
            variant={isEnrolled ? "secondary" : "default"}
            className="w-full min-h-11"
            disabled={isEnrolled || enrolling}
            onClick={() => !isEnrolled && onEnroll(course.id)}
          >
            {isEnrolled ? (
              <span className="flex items-center gap-1">
                <CheckCircle className="h-4 w-4" />
                {t("enrolled")}
              </span>
            ) : enrolling ? (
              t("loading")
            ) : (
              t("enroll")
            )}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
