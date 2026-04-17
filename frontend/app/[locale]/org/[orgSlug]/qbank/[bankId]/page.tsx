import { QBankDetailClient } from "./client";

export default async function Page({
  params,
}: {
  params: Promise<{ bankId: string }>;
}) {
  const { bankId } = await params;
  return <QBankDetailClient bankId={bankId} />;
}
