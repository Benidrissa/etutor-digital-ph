import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { QBankTestResults } from '@/components/qbank/qbank-test-results';
import { getQBankTest, getQBankAttempt, getQBankAttemptHistory } from '@/lib/api';
import type { QBankAttemptSummary } from '@/lib/api';

interface ResultsPageProps {
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
  return { title: t('results.pageTitle') };
}

export default async function QBankTestResultsPage({
  params,
  searchParams,
}: ResultsPageProps) {
  const { testId } = await params;
  const { attempt: attemptId } = await searchParams;

  if (!attemptId) {
    notFound();
  }

  const id = attemptId as string;

  const [test, attempt, history] = await Promise.all([
    getQBankTest(testId).catch(() => null),
    getQBankAttempt(testId, id).catch(() => null),
    getQBankAttemptHistory(testId).catch((): QBankAttemptSummary[] => []),
  ]);

  if (!test || !attempt) {
    notFound();
  }

  return (
    <QBankTestResults
      testId={testId}
      testTitle={test.title}
      attempt={attempt}
      passingScore={test.passing_score}
      history={history}
    />
  );
}
