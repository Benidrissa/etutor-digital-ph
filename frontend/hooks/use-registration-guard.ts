'use client';

import { useEffect } from 'react';
import { useRouter } from '@/i18n/routing';
import { useSettings } from '@/lib/settings-context';

/**
 * Redirects to /login if self-registration is disabled.
 * Returns true when still loading or redirecting (caller should render nothing).
 */
export function useRegistrationGuard(): boolean {
  const { getSetting, loading } = useSettings();
  const registrationEnabled = getSetting<boolean>('auth-self-registration-enabled', false);
  const router = useRouter();

  useEffect(() => {
    if (!loading && !registrationEnabled) {
      router.replace('/login');
    }
  }, [loading, registrationEnabled, router]);

  return loading || !registrationEnabled;
}
