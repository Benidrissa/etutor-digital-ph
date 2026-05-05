"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { QualityStatus, RunStatus } from "@/lib/api-quality";

const UNIT_STATUS_VARIANT: Record<
  QualityStatus,
  "default" | "secondary" | "destructive" | "outline" | "ghost"
> = {
  pending: "outline",
  scoring: "secondary",
  passing: "default",
  needs_review: "secondary",
  regenerating: "secondary",
  needs_review_final: "destructive",
  manual_override: "ghost",
  failed: "destructive",
};

const RUN_STATUS_VARIANT: Record<
  RunStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  scoring: "secondary",
  regenerating: "secondary",
  completed: "default",
  failed: "destructive",
  cancelled: "outline",
};

export function QualityStatusBadge({ status }: { status: QualityStatus }) {
  const t = useTranslations("Admin.qualityAgent.unitStatus");
  return <Badge variant={UNIT_STATUS_VARIANT[status]}>{t(status)}</Badge>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const t = useTranslations("Admin.qualityAgent.runStatus");
  return <Badge variant={RUN_STATUS_VARIANT[status]}>{t(status)}</Badge>;
}
