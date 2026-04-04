import { getTranslations } from "next-intl/server";

interface ExpertDashboardPageProps {
  params: Promise<{ locale: string }>;
}

export default async function ExpertDashboardPage({ params }: ExpertDashboardPageProps) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Expert" });

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-bold">{t("dashboard")}</h1>
        <p className="text-muted-foreground">{t("dashboardDescription")}</p>
      </div>
    </div>
  );
}
