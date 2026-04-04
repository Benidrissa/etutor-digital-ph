import { getTranslations } from 'next-intl/server';
import { TaxonomyClient } from '@/components/admin/taxonomy-client';

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
