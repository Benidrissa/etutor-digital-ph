import { getTranslations } from 'next-intl/server';
import { GroupsClient } from '@/components/admin/groups-client';

export async function generateMetadata() {
  const t = await getTranslations('Admin.groups');
  return {
    title: t('title'),
    description: t('subtitle'),
  };
}

export default async function AdminGroupsPage() {
  const t = await getTranslations('Admin.groups');
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
      </div>
      <GroupsClient />
    </div>
  );
}
