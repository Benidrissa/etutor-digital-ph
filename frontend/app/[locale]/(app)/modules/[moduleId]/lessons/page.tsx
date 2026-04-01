import { redirect } from 'next/navigation';
import { getLocale } from 'next-intl/server';

interface LessonsIndexPageProps {
  params: Promise<{ moduleId: string }>;
}

export default async function LessonsIndexPage({ params }: LessonsIndexPageProps) {
  const { moduleId } = await params;
  const locale = await getLocale();
  redirect(`/${locale}/modules/${moduleId}`);
}
