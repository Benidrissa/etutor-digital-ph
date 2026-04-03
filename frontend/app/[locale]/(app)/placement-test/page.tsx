import { PlacementTestContainer } from '@/components/placement/placement-test-container';
import { PlacementResultsHistory } from '@/components/placement/placement-results-history';

interface PlacementTestPageProps {
  params: Promise<{ locale: string }>;
}

export default async function PlacementTestPage({ params }: PlacementTestPageProps) {
  const { locale } = await params;

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl space-y-8">
      <PlacementTestContainer locale={locale} />
      <PlacementResultsHistory />
    </div>
  );
}
