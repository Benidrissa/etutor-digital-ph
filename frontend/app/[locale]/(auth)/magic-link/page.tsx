'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/routing';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { authClient, AuthError, RegisterResponse } from '@/lib/auth';

export default function MagicLinkPage() {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const router = useRouter();
  const searchParams = useSearchParams();
  
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [error, setError] = useState<string>('');
  const [registerResponse, setRegisterResponse] = useState<RegisterResponse | null>(null);

  useEffect(() => {
    const verifyMagicLink = async () => {
      const token = searchParams.get('token');
      
      if (!token) {
        setStatus('error');
        setError(t('magicLinkInvalid'));
        return;
      }

      try {
        const response = await authClient.verifyMagicLink(token);
        setRegisterResponse(response);
        setStatus('success');
      } catch (error) {
        console.error('Magic link verification error:', error);
        
        setStatus('error');
        if (error instanceof AuthError) {
          setError(error.message);
        } else {
          setError(t('magicLinkFailed'));
        }
      }
    };

    verifyMagicLink();
  }, [searchParams, t]);

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
            <CardDescription>{t('verifyingMagicLink')}</CardDescription>
          </CardHeader>
          <CardContent className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
            <p className="mt-4 text-sm text-muted-foreground">
              {tCommon('loading')}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl text-red-600">{t('magicLinkError')}</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground text-center">
              {t('magicLinkErrorDesc')}
            </p>
            
            <div className="space-y-2">
              <Button
                onClick={() => router.push('/login')}
                className="w-full"
              >
                {t('backToLogin')}
              </Button>
              
              <Button
                variant="outline"
                onClick={() => router.push('/register')}
                className="w-full"
              >
                {t('createNewAccount')}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Success - show TOTP setup (similar to registration)
  if (registerResponse) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl text-green-600">{t('accountRecovered')}</CardTitle>
            <CardDescription>{t('setupNewAuthenticator')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* QR Code */}
            <div className="space-y-4">
              <div className="text-center">
                <img
                  src={`data:image/png;base64,${registerResponse.qr_code}`}
                  alt="QR Code for Authenticator App"
                  className="mx-auto border rounded-lg"
                  style={{ maxWidth: '200px' }}
                />
              </div>
              
              {/* Manual Entry Instructions */}
              <div className="space-y-2">
                <p className="text-sm text-center text-muted-foreground">
                  {t('cantScanQR')}
                </p>
                <details className="text-sm">
                  <summary className="cursor-pointer text-primary">{t('manualEntry')}</summary>
                  <div className="mt-2 p-2 bg-muted rounded text-xs font-mono break-all">
                    {registerResponse.secret}
                  </div>
                </details>
              </div>

              {/* Backup Codes */}
              <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-sm font-medium text-amber-800 mb-2">
                  {t('newBackupCodes')}
                </p>
                <div className="grid grid-cols-2 gap-1 text-xs font-mono">
                  {registerResponse.backup_codes.map((code, index) => (
                    <div key={index} className="bg-white p-1 rounded border">
                      {code}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="text-center">
              <Button
                onClick={() => router.push('/login')}
                className="w-full"
              >
                {t('continueToLogin')}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return null;
}