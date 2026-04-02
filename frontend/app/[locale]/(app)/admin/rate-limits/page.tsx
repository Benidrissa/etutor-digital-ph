import { getTranslations } from "next-intl/server";
import { AdminRateLimitsClient } from "./rate-limits-client";

export default async function AdminRateLimitsPage() {
  const t = await getTranslations("AdminRateLimits");

  return (
    <div className="container max-w-4xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">{t("subtitle")}</p>
      </div>
      <AdminRateLimitsClient />
    </div>
  );
}
