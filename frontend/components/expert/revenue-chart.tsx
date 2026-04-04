"use client";

import { useTranslations } from "next-intl";

interface MonthlyRevenue {
  month: string;
  gross: number;
  commission: number;
  net: number;
}

interface RevenueChartProps {
  data: MonthlyRevenue[];
}

export function RevenueChart({ data }: RevenueChartProps) {
  const t = useTranslations("ExpertRevenue.chart");

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        {t("noData")}
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.gross), 1);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-primary" />
          {t("gross")}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-500" />
          {t("commission")}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" />
          {t("net")}
        </span>
      </div>
      <div
        className="flex items-end gap-1 overflow-x-auto pb-2"
        role="img"
        aria-label={t("title")}
      >
        {data.map((item) => {
          const grossPct = (item.gross / maxValue) * 100;
          const commissionPct = (item.commission / maxValue) * 100;
          const netPct = (item.net / maxValue) * 100;
          return (
            <div key={item.month} className="flex min-w-[2.5rem] flex-1 flex-col items-center gap-1">
              <div className="flex w-full items-end justify-center gap-0.5" style={{ height: "120px" }}>
                <div
                  className="w-2.5 rounded-t bg-primary transition-all"
                  style={{ height: `${grossPct}%` }}
                  title={`${t("gross")}: ${item.gross.toFixed(2)}`}
                />
                <div
                  className="w-2.5 rounded-t bg-amber-500 transition-all"
                  style={{ height: `${commissionPct}%` }}
                  title={`${t("commission")}: ${item.commission.toFixed(2)}`}
                />
                <div
                  className="w-2.5 rounded-t bg-emerald-500 transition-all"
                  style={{ height: `${netPct}%` }}
                  title={`${t("net")}: ${item.net.toFixed(2)}`}
                />
              </div>
              <span className="text-[10px] text-muted-foreground">{item.month}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
