import { getTranslations } from "next-intl/server";
import { UserListClient } from "@/components/admin/user-list-client";

export default async function AdminUsersPage() {
  const t = await getTranslations("Admin.users");

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="mt-1 mb-6 text-muted-foreground">{t("subtitle")}</p>
      <UserListClient />
    </div>
  );
}
