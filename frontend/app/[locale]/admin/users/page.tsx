import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { UserListClient } from "@/components/admin/user-list-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Admin.users" });
  return { title: t("title") };
}

export default async function AdminUsersPage() {
  const t = await getTranslations("Admin.users");

  return (
    <div className="p-4 md:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>
      </div>
      <UserListClient />
    </div>
  );
}
