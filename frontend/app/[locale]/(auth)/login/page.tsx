'use client';

import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { PasswordLoginForm } from '@/components/auth/password-login-form';
import { TOTPLoginForm } from '@/components/auth/totp-login-form';

export default function LoginPage() {
  const [useAuthenticator, setUseAuthenticator] = useState(false);
  const t = useTranslations('Auth');
  const searchParams = useSearchParams();
  const raw = searchParams.get('redirect');
  // Strip locale prefix since router.push() from @/i18n/routing adds it automatically
  const redirectTo = raw?.replace(/^\/(fr|en)/, '') || undefined;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md space-y-3">
        {useAuthenticator ? (
          <>
            <TOTPLoginForm redirectTo={redirectTo} />
            <div className="text-center">
              <button
                onClick={() => setUseAuthenticator(false)}
                className="text-sm text-muted-foreground hover:text-foreground hover:underline min-h-[44px] px-4"
              >
                {t('usePasswordLogin')}
              </button>
            </div>
          </>
        ) : (
          <>
            <PasswordLoginForm redirectTo={redirectTo} />
            <div className="text-center">
              <button
                onClick={() => setUseAuthenticator(true)}
                className="text-sm text-muted-foreground hover:text-foreground hover:underline min-h-[44px] px-4"
              >
                {t('useAuthenticatorLogin')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
