import { getTranslations } from "next-intl/server";
import { SummaryCards } from "@/components/expert/summary-cards";

export async function generateMetadata() {
  const t = await getTranslations("ExpertDashboard");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function ExpertDashboardPage() {
  const t = await getTranslations("ExpertDashboard");

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t("pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("pageDescription")}</p>
      </div>
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <SummaryCards />
      </div>
    </div>
  );
}
