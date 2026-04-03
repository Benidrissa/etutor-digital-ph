import { getTranslations } from "next-intl/server";

export default async function AdminUsersPage() {
  const t = await getTranslations("Admin");

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("users.title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("users.subtitle")}</p>
    </div>
  );
}
