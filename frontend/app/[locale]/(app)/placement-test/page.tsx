import { getTranslations } from 'next-intl/server';
import { PlacementTestContainer } from '@/components/placement/placement-test-container';

interface PlacementTestPageProps {
  params: {
    locale: string;
  };
}

export default async function PlacementTestPage({ params }: PlacementTestPageProps) {
  const t = await getTranslations('PlacementTest');

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <PlacementTestContainer locale={params.locale} />
    </div>
  );
}