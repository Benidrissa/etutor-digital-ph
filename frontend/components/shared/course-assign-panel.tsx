"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Check, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

interface CourseBasic {
  id: string;
  slug?: string;
  title_fr: string;
  title_en: string;
  status?: string;
}

/**
 * Reusable course assignment panel — used by admin curricula and org curricula.
 *
 * @param coursesUrl       API endpoint to fetch available courses
 * @param currentCourseIds IDs of courses already assigned
 * @param onSave           Callback with selected course IDs
 * @param onClose          Close the panel
 * @param saving           Whether a save is in progress
 */
export function CourseAssignPanel({
  coursesUrl,
  currentCourseIds,
  onSave,
  onClose,
  saving,
}: {
  coursesUrl: string;
  currentCourseIds: string[];
  onSave: (courseIds: string[]) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const t = useTranslations("Admin.curricula");
  const locale = useLocale() as "fr" | "en";

  const { data: allCourses = [], isLoading } = useQuery<CourseBasic[]>({
    queryKey: ["courses-for-assign", coursesUrl],
    queryFn: () => apiFetch(coursesUrl),
  });

  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(currentCourseIds)
  );

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card className="p-4 border-2 border-blue-200 bg-blue-50/30">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-medium">{t("assignCourses")}</p>
          <p className="text-xs text-muted-foreground">{t("assignCoursesDesc")}</p>
        </div>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      {isLoading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="max-h-56 overflow-y-auto space-y-1 mb-3">
          {allCourses.map((course) => {
            const title = locale === "fr" ? course.title_fr : course.title_en;
            const isSelected = selected.has(course.id);
            return (
              <button
                key={course.id}
                type="button"
                onClick={() => toggle(course.id)}
                className={`w-full flex items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors min-h-11 ${
                  isSelected
                    ? "bg-teal-50 border-teal-300 text-teal-900"
                    : "border-stone-200 hover:border-stone-300 hover:bg-stone-50 bg-white"
                }`}
              >
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                    isSelected
                      ? "bg-teal-600 border-teal-600 text-white"
                      : "border-stone-300 bg-white"
                  }`}
                >
                  {isSelected && <Check className="h-3 w-3" />}
                </span>
                <span className="flex-1 min-w-0 truncate">{title}</span>
                {course.status && (
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    {course.status}
                  </Badge>
                )}
              </button>
            );
          })}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
          {t("cancel")}
        </Button>
        <Button size="sm" onClick={() => onSave([...selected])} disabled={saving}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
          {t("save")} ({selected.size})
        </Button>
      </div>
    </Card>
  );
}
