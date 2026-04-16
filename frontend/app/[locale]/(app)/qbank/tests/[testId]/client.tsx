'use client';

import { QBankTestPlayer } from '@/components/qbank/qbank-test-player';

export function QBankTestPlayerPage({ testId }: { testId: string }) {
  return <QBankTestPlayer testId={testId} />;
}
