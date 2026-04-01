'use client';

import { useEffect, useState } from 'react';
import { useLocale } from 'next-intl';
import { authClient } from '@/lib/auth';
import { OfflineDownloadDialog } from './offline-download-dialog';

interface OfflineDownloadButtonProps {
  moduleId: string;
  moduleTitleFr: string;
  moduleTitleEn: string;
}

export function OfflineDownloadButton({
  moduleId,
  moduleTitleFr,
  moduleTitleEn,
}: OfflineDownloadButtonProps) {
  const locale = useLocale() as 'fr' | 'en';
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    authClient.getValidToken().then(setToken).catch(() => setToken(null));
  }, []);

  if (!token) return null;

  return (
    <OfflineDownloadDialog
      moduleId={moduleId}
      moduleTitleFr={moduleTitleFr}
      moduleTitleEn={moduleTitleEn}
      locale={locale}
      token={token}
    />
  );
}
