import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { QBankReviewMode } from '@/components/qbank/qbank-review-mode';
import { getQBankTest, getQBankAttempt } from '@/lib/api';

interface ReviewPageProps {
  params: Promise<{ locale: string; testId: string }>;
  searchParams: Promise<{ attempt?: string }>;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; testId: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'QBank' });
  return { title: t('review.pageTitle') };
}

export default async function QBankReviewPage({
  params,
  searchParams,
}: ReviewPageProps) {
  const { testId } = await params;
  const { attempt: attemptId } = await searchParams;

  if (!attemptId) {
    notFound();
  }

  const id = attemptId as string;

  const [test, attempt] = await Promise.all([
    getQBankTest(testId).catch(() => null),
    getQBankAttempt(testId, id).catch(() => null),
  ]);

  if (!test || !attempt) {
    notFound();
  }

  return (
    <QBankReviewMode
      testId={testId}
      testTitle={test.title}
      questions={attempt.question_results}
    />
  );
}
