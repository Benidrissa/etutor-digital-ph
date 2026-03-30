import { getTranslations } from "next-intl/server";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default async function DashboardPage() {
  const t = await getTranslations("Dashboard");

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>{t("streak")}</CardDescription>
            <CardTitle className="text-3xl">0</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>{t("nextReview")}</CardDescription>
            <CardTitle className="text-lg">—</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>{t("continueModule")}</CardDescription>
            <CardTitle className="text-lg">—</CardTitle>
          </CardHeader>
        </Card>
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
