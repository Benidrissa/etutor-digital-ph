import { redirect } from "next/navigation";

export default async function ExpertPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect(`/${locale}/expert/revenue`);
}
