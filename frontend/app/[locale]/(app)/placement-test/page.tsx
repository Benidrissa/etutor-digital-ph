import { redirect } from 'next/navigation';

interface PlacementTestPageProps {
  params: Promise<{ locale: string }>;
}

export default async function PlacementTestPage({ params }: PlacementTestPageProps) {
  const { locale } = await params;
  redirect(`/${locale}/courses`);
}
