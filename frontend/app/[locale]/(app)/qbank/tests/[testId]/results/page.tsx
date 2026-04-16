import { QBankTestResultsPage } from './client';

export default async function QBankResultsPage({
  params,
  searchParams,
}: {
  params: Promise<{ testId: string }>;
  searchParams: Promise<{ attempt_id?: string }>;
}) {
  const { testId } = await params;
  const { attempt_id } = await searchParams;
  return <QBankTestResultsPage testId={testId} attemptId={attempt_id} />;
}
