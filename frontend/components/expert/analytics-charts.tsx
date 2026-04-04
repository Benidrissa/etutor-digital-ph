"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Loader2, AlertCircle, TrendingUp, CheckCircle, Users } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

interface CourseAnalytics {
  quiz_pass_rate: number;
  average_quiz_score: number;
  funnel: {
    enrolled: number;
    started: number;
    half_complete: number;
    completed: number;
  };
  time_spent_distribution: TimeSpentBucket[];
}

interface TimeSpentBucket {
  label: string;
  count: number;
}

function useAnalytics(courseId: string) {
  return useQuery<CourseAnalytics>({
    queryKey: ["expert", "courses", courseId, "analytics"],
    queryFn: () => apiFetch<CourseAnalytics>(`/api/v1/expert/courses/${courseId}/analytics`),
  });
}

interface BarProps {
  value: number;
  max: number;
  label: string;
  count: number;
}

function FunnelBar({ value, max, label, count }: BarProps) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <p className="text-xs text-muted-foreground w-20 shrink-0 text-right">{label}</p>
      <div className="flex-1 h-6 rounded bg-muted relative overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-primary/80 rounded transition-all"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={value}
          aria-valuemax={max}
          aria-label={label}
        />
      </div>
      <span className="text-xs font-medium w-10 shrink-0">{count}</span>
    </div>
  );
}

function ScoreGauge({ value, label }: { value: number; label: string }) {
  const clampedValue = Math.min(100, Math.max(0, value));
  const circumference = 2 * Math.PI * 40;
  const offset = circumference - (clampedValue / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative h-24 w-24">
        <svg className="h-24 w-24 -rotate-90" viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="10" className="text-muted" />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="currentColor"
            strokeWidth="10"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className="text-primary transition-all duration-500"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xl font-bold">{Math.round(clampedValue)}%</span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground text-center">{label}</p>
    </div>
  );
}

interface AnalyticsChartsProps {
  courseId: string;
}

export function AnalyticsCharts({ courseId }: AnalyticsChartsProps) {
  const t = useTranslations("ExpertAnalytics");
  const { data, isLoading, error, refetch } = useAnalytics(courseId);

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

  if (!data) return null;

  const funnelMax = data.funnel.enrolled;

  const funnelSteps = [
    { label: t("funnel.enrolled"), count: data.funnel.enrolled },
    { label: t("funnel.started"), count: data.funnel.started },
    { label: t("funnel.halfComplete"), count: data.funnel.half_complete },
    { label: t("funnel.completed"), count: data.funnel.completed },
  ];

  const maxBucketCount = data.time_spent_distribution.reduce(
    (max, b) => Math.max(max, b.count),
    0
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <Card className="p-4 flex flex-col items-center gap-2">
          <div className="rounded-md bg-green-100 p-2">
            <CheckCircle className="h-5 w-5 text-green-700" aria-hidden="true" />
          </div>
          <ScoreGauge value={data.quiz_pass_rate} label={t("quizPassRate")} />
        </Card>

        <Card className="p-4 flex flex-col items-center gap-2">
          <div className="rounded-md bg-blue-100 p-2">
            <TrendingUp className="h-5 w-5 text-blue-700" aria-hidden="true" />
          </div>
          <ScoreGauge value={data.average_quiz_score} label={t("avgQuizScore")} />
        </Card>
      </div>

      <Card className="p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Users className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          <h3 className="text-sm font-semibold">{t("completionFunnel")}</h3>
        </div>
        <div className="space-y-3">
          {funnelSteps.map((step) => (
            <FunnelBar
              key={step.label}
              label={step.label}
              count={step.count}
              value={step.count}
              max={funnelMax}
            />
          ))}
        </div>
      </Card>

      {data.time_spent_distribution.length > 0 && (
        <Card className="p-4 space-y-4">
          <h3 className="text-sm font-semibold">{t("timeSpentDistribution")}</h3>
          <div className="flex items-end gap-2 h-32">
            {data.time_spent_distribution.map((bucket) => {
              const heightPct = maxBucketCount > 0 ? (bucket.count / maxBucketCount) * 100 : 0;
              return (
                <div
                  key={bucket.label}
                  className="flex flex-col items-center gap-1 flex-1 min-w-0"
                  title={`${bucket.label}: ${bucket.count}`}
                >
                  <div className="w-full flex items-end justify-center h-24">
                    <div
                      className="w-full max-w-[28px] rounded-t bg-primary/70"
                      style={{ height: `${heightPct}%` }}
                      role="img"
                      aria-label={`${bucket.label}: ${bucket.count}`}
                    />
                  </div>
                  <span className="text-[10px] text-muted-foreground text-center truncate w-full">
                    {bucket.label}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground text-center">{t("timeSpentUnit")}</p>
        </Card>
      )}
    </div>
  );
}
