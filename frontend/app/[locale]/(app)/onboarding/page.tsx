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

interface OnboardingPageProps {
  params: {
    locale: string;
  };
}

export default async function OnboardingPage({ params }: OnboardingPageProps) {
  const t = await getTranslations('Common');

  return (
    <div className="container mx-auto px-4 py-8">
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Welcome to {t('appName')}!</CardTitle>
          <CardDescription>
            Your registration is complete. Let&apos;s get you started on your public health learning journey.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-center text-muted-foreground">
            This onboarding flow will be implemented in a future update.
          </p>
          <Link href={`/${params.locale}/dashboard`}>
            <Button className="w-full min-h-11">
              Go to Dashboard
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}