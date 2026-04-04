import { getTranslations } from "next-intl/server";
import { RevenueClient } from "@/components/expert/revenue-client";

export default async function ExpertRevenuePage() {
  const t = await getTranslations("ExpertRevenue");

  return (
    <div className="p-4 md:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>
      </div>
      <RevenueClient />
    </div>
  );
}
