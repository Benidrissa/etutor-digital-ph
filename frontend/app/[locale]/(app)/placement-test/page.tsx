import { getTranslations } from 'next-intl/server';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import Link from 'next/link';

interface PlacementTestPageProps {
  params: {
    locale: string;
  };
}

export default async function PlacementTestPage({ params }: PlacementTestPageProps) {
  const t = await getTranslations('Common');

  return (
    <div className="container mx-auto px-4 py-8">
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Diagnostic Assessment</CardTitle>
          <CardDescription>
            Complete this assessment to help us personalize your learning experience.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-center text-muted-foreground">
            The diagnostic assessment will be implemented in a future update.
          </p>
          <Link href={`/${params.locale}/dashboard`}>
            <Button className="w-full min-h-11">
              Skip for now - Go to Dashboard
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}