import { getTranslations } from "next-intl/server";
import { UserDetailClient } from "@/components/admin/user-detail-client";

export default async function AdminUserDetailPage({
  params,
}: {
  params: Promise<{ locale: string; userId: string }>;
}) {
  const { userId } = await params;
  const t = await getTranslations("Admin.userDetail");

  return (
    <div className="p-4 md:p-6">
      <h1 className="sr-only">{t("title")}</h1>
      <UserDetailClient userId={userId} />
    </div>
  );
}
