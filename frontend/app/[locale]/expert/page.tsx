import { redirect } from "next/navigation";

interface ExpertPageProps {
  params: Promise<{ locale: string }>;
}

export default async function ExpertPage({ params }: ExpertPageProps) {
  const { locale } = await params;
  redirect(`/${locale}/expert/dashboard`);
}
