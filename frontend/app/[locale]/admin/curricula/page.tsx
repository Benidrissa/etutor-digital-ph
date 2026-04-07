import { getTranslations } from 'next-intl/server';
import { CurriculaClient } from '@/components/admin/curricula-client';

export async function generateMetadata() {
  const t = await getTranslations('AdminCurricula');
  return {
    title: t('pageTitle'),
    description: t('pageDescription'),
  };
}

export default async function AdminCurriculaPage() {
  const t = await getTranslations('AdminCurricula');
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t('pageTitle')}</h1>
        <p className="text-muted-foreground mt-1">{t('pageDescription')}</p>
      </div>
      <CurriculaClient />
    </div>
  );
}
