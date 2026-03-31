'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
import { z } from 'zod';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { authClient, AuthError } from '@/lib/auth';

const createLoginSchema = (t: (key: string) => string) => z.object({
  email: z.string().min(1, t('emailRequired')).email(t('emailInvalid')),
  totp_code: z
    .string()
    .min(6, t('codeRequired'))
    .max(8, t('codeInvalid'))
    .regex(/^\d{6,8}$/, t('codeInvalid')),
});

const createMagicLinkSchema = (t: (key: string) => string) => z.object({
  email: z.string().min(1, t('emailRequired')).email(t('emailInvalid')),
});

type LoginForm = z.infer<ReturnType<typeof createLoginSchema>>;
type MagicLinkForm = z.infer<ReturnType<typeof createMagicLinkSchema>>;

export function TOTPLoginForm() {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const router = useRouter();
  const locale = useLocale();
  
  const [isLoading, setIsLoading] = useState(false);
  const [showMagicLink, setShowMagicLink] = useState(false);
  const [magicLinkSent, setMagicLinkSent] = useState(false);

  // Login form
  const loginSchema = createLoginSchema(t);
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
    watch,
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
  });

  // Magic link form
  const magicLinkSchema = createMagicLinkSchema(t);
  const {
    register: registerMagic,
    handleSubmit: handleMagicSubmit,
    formState: { errors: magicErrors },
    setError: setMagicError,
  } = useForm<MagicLinkForm>({
    resolver: zodResolver(magicLinkSchema),
  });

  const totpCode = watch('totp_code');
  const isBackupCode = totpCode && totpCode.length === 8;

  const onLoginSubmit = async (data: LoginForm) => {
    setIsLoading(true);
    
    try {
      await authClient.login({
        email: data.email,
        totp_code: data.totp_code,
      });
      
      // Login successful - redirect to dashboard
      router.push(`/${locale}/dashboard`);
    } catch (error) {
      console.error('Login error:', error);
      
      if (error instanceof AuthError) {
        if (error.message.includes('credentials')) {
          setError('email', { message: t('invalidCredentials') });
        } else if (error.message.includes('authentication code')) {
          setError('totp_code', { message: t('invalidCode') });
        } else if (error.message.includes('MFA not set up')) {
          setError('email', { message: t('mfaNotSetup') });
        } else {
          setError('root', { message: error.message });
        }
      } else {
        setError('root', { message: t('loginFailed') });
      }
    } finally {
      setIsLoading(false);
    }
  };

  const onMagicLinkSubmit = async (data: MagicLinkForm) => {
    setIsLoading(true);
    
    try {
      await authClient.sendMagicLink(data.email);
      setMagicLinkSent(true);
    } catch (error) {
      console.error('Magic link error:', error);
      
      if (error instanceof AuthError) {
        setMagicError('root', { message: error.message });
      } else {
        setMagicError('root', { message: t('magicLinkFailed') });
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Magic link sent confirmation
  if (magicLinkSent) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
          <CardDescription className="text-green-600">
            {t('magicLinkSent')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground text-center">
            {t('checkEmailForMagicLink')}
          </p>
          
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => {
              setMagicLinkSent(false);
              setShowMagicLink(false);
            }}
          >
            {t('backToLogin')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // Magic link request form
  if (showMagicLink) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{t('accountRecovery')}</CardTitle>
          <CardDescription>{t('accountRecoveryDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleMagicSubmit(onMagicLinkSubmit)} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="magic-email">
                {t('email')} *
              </label>
              <input
                {...registerMagic('email')}
                id="magic-email"
                type="email"
                autoComplete="email"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder={t('emailPlaceholder')}
              />
              {magicErrors.email && (
                <p className="text-sm text-red-600">{magicErrors.email.message}</p>
              )}
            </div>

            {magicErrors.root && (
              <p className="text-sm text-red-600 text-center">{magicErrors.root.message}</p>
            )}

            <div className="space-y-2">
              <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
                {isLoading ? tCommon('loading') : t('sendMagicLink')}
              </Button>
              
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => setShowMagicLink(false)}
                disabled={isLoading}
              >
                {t('backToLogin')}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    );
  }

  // Main login form
  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
        <CardDescription>{t('signIn')}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onLoginSubmit)} className="space-y-4">
          {/* Email Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="email">
              {t('email')} *
            </label>
            <input
              {...register('email')}
              id="email"
              type="email"
              autoComplete="email"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder={t('emailPlaceholder')}
            />
            {errors.email && (
              <p className="text-sm text-red-600">{errors.email.message}</p>
            )}
          </div>

          {/* TOTP/Backup Code Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="totp_code">
              {isBackupCode ? t('backupCode') : t('authenticatorCode')} *
            </label>
            <input
              {...register('totp_code')}
              id="totp_code"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={8}
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 text-center text-lg tracking-wider"
              placeholder={isBackupCode ? "12345678" : "123456"}
            />
            {errors.totp_code && (
              <p className="text-sm text-red-600">{errors.totp_code.message}</p>
            )}
            <p className="text-xs text-muted-foreground text-center">
              {isBackupCode ? t('backupCodeInstructions') : t('totpLoginInstructions')}
            </p>
          </div>

          {/* Root Error */}
          {errors.root && (
            <p className="text-sm text-red-600 text-center">{errors.root.message}</p>
          )}

          {/* Submit Button */}
          <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
            {isLoading ? tCommon('loading') : t('signIn')}
          </Button>

          {/* Recovery Link */}
          <div className="text-center">
            <button
              type="button"
              onClick={() => setShowMagicLink(true)}
              className="text-sm text-primary hover:underline"
            >
              {t('lostAuthenticator')}
            </button>
          </div>

          {/* Registration Link */}
          <div className="text-center text-sm">
            <span className="text-muted-foreground">{t('noAccount')} </span>
            <Link 
              href={`/${locale}/register`}
              className="font-medium text-primary hover:underline"
            >
              {t('signUp')}
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}