import { getTranslations } from "next-intl/server";
import { DashboardClient } from "./dashboard-client";
import { DashboardStats } from "@/components/dashboard/dashboard-stats";
import { UpcomingReviews } from "@/components/dashboard/upcoming-reviews";
import { CurriculaSection } from "@/components/shared/curricula-section";
import { ClearCurriculumContext } from "@/components/shared/clear-curriculum-context";

interface DashboardPageProps {
  searchParams: Promise<{ curriculum?: string }>;
}

export default async function DashboardPage({ searchParams }: DashboardPageProps) {
  const t = await getTranslations("Dashboard");
  const { curriculum } = await searchParams;

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>

      <div className="mt-6">
        <DashboardStats />
      </div>

      <div className="mt-8">
        <UpcomingReviews />
      </div>

      <div className="mt-8">
        <DashboardClient curriculumSlug={curriculum} />
      </div>

      {!curriculum && <ClearCurriculumContext />}
      {!curriculum && <CurriculaSection />}
    </div>
  );
}
