import { getTranslations } from "next-intl/server";
import { Card, CardContent } from "@/components/ui/card";
import { DashboardStats } from "@/components/dashboard/dashboard-stats";

export default async function DashboardPage() {
  const t = await getTranslations("Dashboard");

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>

      <div className="mt-6">
        <DashboardStats />
      </div>

      <div className="mt-8">
        <h2 className="text-lg font-medium">Modules</h2>
        <Card className="mt-4">
          <CardContent className="py-12 text-center text-muted-foreground">
            Module map coming soon
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
