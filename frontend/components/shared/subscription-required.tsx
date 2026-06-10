'use client';

import type { ReactNode } from 'react';
import { Lock } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/routing';
import { Card, CardContent } from '@/components/ui/card';

interface SubscriptionRequiredProps {
  /** Optional secondary action rendered under the Subscribe CTA (e.g. "back to module"). */
  secondaryAction?: ReactNode;
}

/**
 * Shown when content is gated behind an active subscription (backend 403
 * `subscription_required`). Replaces the generic "load error" state with a
 * clear message and a link to the /subscribe page (#2469).
 */
export function SubscriptionRequired({ secondaryAction }: SubscriptionRequiredProps) {
  const t = useTranslations('SubscriptionRequired');

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      <Card className="border-primary/20">
        <CardContent className="p-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Lock className="h-6 w-6 text-primary" />
          </div>
          <div className="mb-2 font-medium text-stone-900">{t('title')}</div>
          <p className="mx-auto mb-5 max-w-md text-gray-600">{t('description')}</p>
          <div className="flex flex-col items-center gap-3">
            <Link
              href="/subscribe"
              className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
            >
              {t('cta')}
            </Link>
            {secondaryAction}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
