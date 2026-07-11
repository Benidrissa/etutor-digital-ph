"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface AiUsageTotals {
  cost_cents: number;
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  estimated_cost_share: number;
}

interface AiUsageResponse {
  period: string;
  totals: AiUsageTotals;
  top_model: string | null;
  daily_costs: ({ date: string } & Record<string, number | string>)[];
  by_model: {
    model: string;
    provider: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_cents: number;
    estimated: boolean;
  }[];
  by_feature: { feature: string; calls: number; cost_cents: number; tokens: number }[];
  by_user: { user_id: string; email: string; calls: number; cost_cents: number }[];
  by_key_source: { source: string; calls: number; cost_cents: number }[];
  errors_by_feature: { feature: string; count: number; cost_cents: number }[];
  recommendations: { code: string; severity: "info" | "warning"; data: Record<string, unknown> }[];
}

// Fixed provider→color map (Okabe-Ito subset, CVD-safe; validated light+dark).
// Color follows the entity — a provider keeps its hue whatever else is shown.
const PROVIDER_COLORS: Record<string, string> = {
  openai: "#0072B2",
  anthropic: "#E69F00",
  moonshot: "#009E73",
  google: "#CC79A7",
  openrouter: "#56B4E9",
};
const PROVIDER_ORDER = ["openai", "anthropic", "moonshot", "google", "openrouter"];

const compactNumber = new Intl.NumberFormat(undefined, { notation: "compact" });

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function AiCostsTab({ period }: { period: number }) {
  const t = useTranslations("Admin.analytics");
  const [data, setData] = useState<AiUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const result = await apiFetch<AiUsageResponse>(
        `/api/v1/analytics/ai-usage?period=${p}`
      );
      setData(result);
    } catch (err) {
      console.error("[admin/analytics] Failed to fetch AI usage:", err);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(period);
  }, [period, fetchData]);

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

  const hasEstimates = data.totals.estimated_cost_share > 0;
  const activeProviders = PROVIDER_ORDER.filter((p) =>
    data.daily_costs.some((d) => typeof d[p] === "number" && (d[p] as number) > 0)
  );
  const featureLabel = (f: string) => (t.has(`feature.${f}`) ? t(`feature.${f}`) : f);
  const byFeatureData = data.by_feature.map((f) => ({
    ...f,
    name: featureLabel(f.feature),
    cost: Number((f.cost_cents / 100).toFixed(4)),
  }));
  const byModelData = data.by_model.map((m) => ({
    ...m,
    name: m.estimated ? `${m.model} ≈` : m.model,
    cost: Number((m.cost_cents / 100).toFixed(4)),
  }));
  const dailyUsd = data.daily_costs.map((d) => {
    const row: Record<string, number | string> = { date: d.date as string };
    for (const p of activeProviders) {
      row[p] = Number((((d[p] as number) || 0) / 100).toFixed(4));
    }
    return row;
  });

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("totalCost")}</p>
            <p className="text-3xl font-bold">
              {formatUsd(data.totals.cost_cents)}
              {hasEstimates && (
                <span
                  className="ml-1 text-base font-normal text-muted-foreground"
                  title={t("estimatedBadge")}
                >
                  ≈
                </span>
              )}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("totalTokens")}</p>
            <p className="text-3xl font-bold">
              {compactNumber.format(data.totals.input_tokens + data.totals.output_tokens)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("totalCalls")}</p>
            <p className="text-3xl font-bold">{data.totals.calls.toLocaleString()}</p>
            {data.totals.errors > 0 && (
              <p className="text-xs text-destructive mt-1">
                {t("errorsCount", { count: data.totals.errors })}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{t("topModel")}</p>
            <p className="text-xl font-bold break-all">{data.top_model ?? "—"}</p>
          </CardContent>
        </Card>
      </div>

      {/* Daily cost stacked by provider */}
      {dailyUsd.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("costByDay")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full">
              <ResponsiveContainer width="100%" height={256}>
                <BarChart data={dailyUsd}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(v) => {
                      const d = new Date(v);
                      return `${d.getMonth() + 1}/${d.getDate()}`;
                    }}
                  />
                  <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(value) => `$${Number(value).toFixed(2)}`} />
                  <Legend />
                  {activeProviders.map((p) => (
                    <Bar key={p} dataKey={p} stackId="cost" fill={PROVIDER_COLORS[p]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cost by model */}
      {byModelData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("costByModel")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full">
              <ResponsiveContainer width="100%" height={256}>
                <BarChart data={byModelData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-25} textAnchor="end" height={70} />
                  <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(value) => `$${Number(value).toFixed(2)}`} />
                  <Bar dataKey="cost" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cost by feature */}
      {byFeatureData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("costByFeature")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full">
              <ResponsiveContainer width="100%" height={256}>
                <BarChart data={byFeatureData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-25} textAnchor="end" height={70} />
                  <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(value) => `$${Number(value).toFixed(2)}`} />
                  <Bar dataKey="cost" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top users by cost + key source */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {data.by_user.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t("topUsersByCost")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left">
                      <th className="pb-2 font-medium text-muted-foreground">{t("userEmail")}</th>
                      <th className="pb-2 font-medium text-muted-foreground text-right">{t("callCount")}</th>
                      <th className="pb-2 font-medium text-muted-foreground text-right">{t("costHeader")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_user.map((u) => (
                      <tr key={u.user_id} className="border-b last:border-0">
                        <td className="py-2 text-xs break-all">{u.email}</td>
                        <td className="py-2 text-right">{u.calls.toLocaleString()}</td>
                        <td className="py-2 text-right">{formatUsd(u.cost_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
        {data.by_key_source.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t("byKeySource")}</CardTitle>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 font-medium text-muted-foreground">{t("keySourceHeader")}</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">{t("callCount")}</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">{t("costHeader")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_key_source.map((s) => (
                    <tr key={s.source} className="border-b last:border-0">
                      <td className="py-2">
                        {s.source === "tenant" ? t("keySourceTenant") : t("keySourcePlatform")}
                      </td>
                      <td className="py-2 text-right">{s.calls.toLocaleString()}</td>
                      <td className="py-2 text-right">{formatUsd(s.cost_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Money-saving recommendations */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t("recommendationsTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recommendations.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("recoEmpty")}</p>
          ) : (
            <ul className="space-y-3">
              {data.recommendations.map((r) => (
                <li key={r.code} className="flex gap-3 items-start">
                  {r.severity === "warning" ? (
                    <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500 mt-0.5" aria-hidden />
                  ) : (
                    <Info className="h-5 w-5 shrink-0 text-muted-foreground mt-0.5" aria-hidden />
                  )}
                  <div>
                    <p className="text-sm font-medium">
                      {t.has(`reco.${r.code}.title`) ? t(`reco.${r.code}.title`) : r.code}
                    </p>
                    {t.has(`reco.${r.code}.body`) && (
                      <p className="text-sm text-muted-foreground">
                        {t(
                          `reco.${r.code}.body`,
                          Object.fromEntries(
                            Object.entries(r.data).map(([k, v]) => [
                              k,
                              Array.isArray(v) ? v.join(", ") : String(v),
                            ])
                          )
                        )}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {hasEstimates && (
            <p className="text-xs text-muted-foreground mt-4">{t("estimatedNote")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
