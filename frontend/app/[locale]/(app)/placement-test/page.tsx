import { PlacementTestContainer } from '@/components/placement/placement-test-container';

interface PlacementTestPageProps {
  params: Promise<{ locale: string }>;
}

export default async function PlacementTestPage({ params }: PlacementTestPageProps) {
  const { locale } = await params;

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <PlacementTestContainer locale={locale} />
    </div>
  );
}
