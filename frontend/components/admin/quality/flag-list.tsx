"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { FlagSeverity, QualityFlag } from "@/lib/api-quality";

const SEVERITY_ORDER: FlagSeverity[] = ["blocking", "high", "medium", "low"];

const SEVERITY_VARIANT: Record<
  FlagSeverity,
  "default" | "secondary" | "destructive" | "outline"
> = {
  blocking: "destructive",
  high: "destructive",
  medium: "secondary",
  low: "outline",
};

function groupBySeverity(flags: QualityFlag[]): Map<FlagSeverity, QualityFlag[]> {
  const out = new Map<FlagSeverity, QualityFlag[]>();
  for (const f of flags) {
    const list = out.get(f.severity) ?? [];
    list.push(f);
    out.set(f.severity, list);
  }
  return out;
}

export function FlagList({ flags }: { flags: QualityFlag[] }) {
  const t = useTranslations("Admin.qualityAgent");
  const tCat = useTranslations("Admin.qualityAgent.flagCategory");
  const tSev = useTranslations("Admin.qualityAgent.severity");

  if (flags.length === 0) {
    return (
      <div className="rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        {t("unit.noFlags")}
      </div>
    );
  }

  const grouped = groupBySeverity(flags);

  return (
    <div className="space-y-4">
      {SEVERITY_ORDER.flatMap((sev) => {
        const items = grouped.get(sev);
        if (!items || items.length === 0) return [];
        return [
          <section key={sev} className="space-y-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              <Badge variant={SEVERITY_VARIANT[sev]}>{tSev(sev)}</Badge>
              <span>· {items.length}</span>
            </h3>
            <ul className="space-y-2">
              {items.map((f, i) => (
                <li key={`${sev}-${i}`}>
                  <Card className="p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold">{tCat(f.category)}</span>
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                        {f.location}
                      </code>
                    </div>
                    {f.evidence_unit_id && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t("unit.crossUnitRef", { unit: f.evidence_unit_id })}
                      </p>
                    )}
                    <p className="mt-2 text-sm">{f.description}</p>
                    <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted/50 p-2 font-mono text-xs whitespace-pre-wrap break-words">
                      {f.evidence}
                    </pre>
                    <p className="mt-2 text-sm italic text-muted-foreground">
                      <span className="font-medium not-italic">{t("unit.suggestedFix")}:</span>{" "}
                      {f.suggested_fix}
                    </p>
                  </Card>
                </li>
              ))}
            </ul>
          </section>,
        ];
      })}
    </div>
  );
}
