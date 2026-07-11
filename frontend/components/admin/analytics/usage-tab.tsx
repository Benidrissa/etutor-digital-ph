"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface AnalyticsSummary {
  period: string;
  total_events: number;
  unique_users: number;
  events_by_type: Record<string, number>;
  daily_active_users: { date: string; count: number }[];
  top_modules: { module_id: string; event_count: number }[];
  quiz_completion_rate: number;
}

export function UsageTab({ period }: { period: number }) {
  const t = useTranslations("Admin.analytics");
  const tEvent = useTranslations("AnalyticsEventTypes");
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const result = await apiFetch<AnalyticsSummary>(
        `/api/v1/analytics/summary?period=${p}`
      );
      setData(result);
    } catch (err) {
      console.error("[admin/analytics] Failed to fetch summary:", err);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(period);
  }, [period, fetchData]);

  const eventsByTypeData = data
    ? Object.entries(data.events_by_type).map(([name, count]) => ({
        name: tEvent.has(name) ? tEvent(name) : name.replace(/_/g, " "),
        count,
      }))
    : [];

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!data) {
    return <p className="text-muted-foreground text-center py-12">{t("noData")}</p>;
  }

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("totalEvents")}</p>
            <p className="text-3xl font-bold">{data.total_events.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("uniqueUsers")}</p>
            <p className="text-3xl font-bold">{data.unique_users.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("quizCompletionRate")}</p>
            <p className="text-3xl font-bold">{(data.quiz_completion_rate * 100).toFixed(1)}%</p>
          </CardContent>
        </Card>
      </div>

      {/* DAU chart */}
      {data.daily_active_users.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("dailyActiveUsers")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full">
              <ResponsiveContainer width="100%" height={256}>
                <LineChart data={data.daily_active_users}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(v) => {
                      const d = new Date(v);
                      return `${d.getMonth() + 1}/${d.getDate()}`;
                    }}
                  />
                  <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Events by type */}
      {eventsByTypeData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("eventsByType")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full">
              <ResponsiveContainer width="100%" height={256}>
                <BarChart data={eventsByTypeData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-25} textAnchor="end" height={60} />
                  <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top modules */}
      {data.top_modules.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("topModules")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 font-medium text-muted-foreground">{t("moduleName")}</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">{t("eventCount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_modules.map((m, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-2 font-mono text-xs">{m.module_id}</td>
                      <td className="py-2 text-right">{m.event_count.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
