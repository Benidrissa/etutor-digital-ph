import { QBankTestPlayerPage } from './client';

export default async function QBankTestPage({ params }: { params: Promise<{ testId: string }> }) {
  const { testId } = await params;
  return <QBankTestPlayerPage testId={testId} />;
}
