import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import { TaxonomyClient } from '@/components/admin/taxonomy-client';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'Admin.taxonomy' });
  return { title: t('title') };
}

export default async function TaxonomyPage() {
  const t = await getTranslations('Admin.taxonomy');

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        <p className="text-sm text-muted-foreground">{t('subtitle')}</p>
      </div>
      <TaxonomyClient />
    </div>
  );
}
