"use client";

import { useTranslations, useLocale } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { BookOpen, Users, TrendingUp, Coins, Loader2, AlertCircle, ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

interface ExpertDashboardSummary {
  total_courses: number;
  active_learners: number;
  monthly_revenue: number;
  credit_balance: number;
  courses: ExpertCourseSummary[];
}

interface ExpertCourseSummary {
  id: string;
  title_fr: string;
  title_en: string;
  learner_count: number;
  completion_rate: number;
}

function useExpertDashboard() {
  return useQuery<ExpertDashboardSummary>({
    queryKey: ["expert", "dashboard"],
    queryFn: () => apiFetch<ExpertDashboardSummary>("/api/v1/expert/dashboard"),
  });
}

export function SummaryCards() {
  const t = useTranslations("ExpertDashboard");
  const locale = useLocale();
  const router = useRouter();

  const { data, isLoading, error, refetch } = useExpertDashboard();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" aria-label={t("loading")} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">{t("errorLoading")}</p>
        <Button variant="outline" onClick={() => refetch()}>
          {t("retry")}
        </Button>
      </div>
    );
  }

  const stats = [
    {
      icon: BookOpen,
      label: t("totalCourses"),
      value: data?.total_courses ?? 0,
    },
    {
      icon: Users,
      label: t("activeLearners"),
      value: data?.active_learners ?? 0,
    },
    {
      icon: TrendingUp,
      label: t("monthlyRevenue"),
      value: `${(data?.monthly_revenue ?? 0).toLocaleString()} FCFA`,
    },
    {
      icon: Coins,
      label: t("creditBalance"),
      value: data?.credit_balance ?? 0,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.label} className="p-4">
              <div className="flex items-start gap-3">
                <div className="rounded-md bg-primary/10 p-2 shrink-0">
                  <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs text-muted-foreground truncate">{stat.label}</p>
                  <p className="text-xl font-bold mt-0.5">{stat.value}</p>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {data?.courses && data.courses.length > 0 && (
        <div>
          <h2 className="text-base font-semibold mb-3">{t("myCourses")}</h2>
          <div className="flex flex-col gap-2">
            {data.courses.map((course) => {
              const title = locale === "fr" ? course.title_fr : course.title_en;
              return (
                <Card key={course.id} className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm truncate">{title}</p>
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="text-xs text-muted-foreground">
                          {t("learnerCount", { count: course.learner_count })}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {t("completionRate", { rate: Math.round(course.completion_rate) })}
                        </span>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0 min-h-11 min-w-11 p-2"
                      onClick={() => router.push(`/${locale}/expert/courses/${course.id}/learners`)}
                      aria-label={t("viewCourse")}
                    >
                      <ChevronRight className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </div>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {(!data?.courses || data.courses.length === 0) && !isLoading && (
        <div className="py-12 text-center">
          <BookOpen className="h-12 w-12 text-muted-foreground mx-auto mb-4" aria-hidden="true" />
          <p className="font-medium text-muted-foreground">{t("noCourses")}</p>
        </div>
      )}
    </div>
  );
}
