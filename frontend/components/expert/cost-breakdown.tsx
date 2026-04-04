"use client";

import { useTranslations } from "next-intl";

interface CourseGenerationCost {
  courseId: string;
  courseTitle: string;
  totalCostUsd: number;
  apiCalls: number;
  lastUsedAt: string | null;
}

interface CostBreakdownProps {
  courses: CourseGenerationCost[];
  loading?: boolean;
  error?: boolean;
}

export function CostBreakdown({ courses, loading, error }: CostBreakdownProps) {
  const t = useTranslations("ExpertCredits.breakdown");

  if (loading) {
    return (
      <p className="py-4 text-sm text-muted-foreground">{t("loading")}</p>
    );
  }

  if (error) {
    return (
      <p className="py-4 text-sm text-destructive">{t("error")}</p>
    );
  }

  if (courses.length === 0) {
    return (
      <p className="py-4 text-sm text-muted-foreground">{t("noCourses")}</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4 font-medium">{t("course")}</th>
            <th className="py-2 pr-4 font-medium text-right">{t("calls")}</th>
            <th className="py-2 pr-4 font-medium text-right">{t("totalCost")}</th>
            <th className="py-2 font-medium">{t("lastUsed")}</th>
          </tr>
        </thead>
        <tbody>
          {courses.map((item) => (
            <tr key={item.courseId} className="border-b last:border-0">
              <td className="py-2.5 pr-4 font-medium">{item.courseTitle}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums">{item.apiCalls}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums">
                ${item.totalCostUsd.toFixed(4)}
              </td>
              <td className="py-2.5 text-muted-foreground">
                {item.lastUsedAt
                  ? new Date(item.lastUsedAt).toLocaleDateString()
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
