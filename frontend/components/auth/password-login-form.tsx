'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslations } from 'next-intl';
import { z } from 'zod';
import { Link, useRouter } from '@/i18n/routing';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { authClient, AuthError } from '@/lib/auth';

const createSchema = (t: (key: string) => string) =>
  z.object({
    identifier: z.string().min(1, t('phoneOrEmailRequired')),
    password: z.string().min(1, t('passwordRequired')),
  });

type FormData = z.infer<ReturnType<typeof createSchema>>;

export function PasswordLoginForm() {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const router = useRouter();

  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const schema = createSchema(t);
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: FormData) => {
    setIsLoading(true);

    try {
      await authClient.loginPassword({
        identifier: data.identifier,
        password: data.password,
      });

      router.push('/dashboard');
    } catch (error) {
      if (error instanceof AuthError) {
        if (
          error.message.toLowerCase().includes('invalid') ||
          error.message.toLowerCase().includes('incorrect') ||
          error.message.toLowerCase().includes('not found') ||
          error.status === 401
        ) {
          setError('root', { message: t('invalidPassword') });
        } else if (
          error.message.toLowerCase().includes('locked') ||
          error.status === 423
        ) {
          setError('root', { message: t('accountLocked') });
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

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
        <CardDescription>{t('signIn')}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="identifier">
              {t('phoneOrEmail')} *
            </label>
            <input
              {...register('identifier')}
              id="identifier"
              type="text"
              autoComplete="email"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder={t('phoneOrEmailPlaceholder')}
            />
            {errors.identifier && (
              <p className="text-sm text-red-600">{errors.identifier.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium" htmlFor="password">
                {t('password')} *
              </label>
              <Link
                href="/magic-link"
                className="text-xs text-primary hover:underline"
              >
                {t('forgotPassword')}
              </Link>
            </div>
            <div className="relative">
              <input
                {...register('password')}
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 pr-12 text-base ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder="••••••"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 min-w-[44px] min-h-[44px] flex items-center justify-center text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
            {errors.password && (
              <p className="text-sm text-red-600">{errors.password.message}</p>
            )}
          </div>

          {errors.root && (
            <p className="text-sm text-red-600 text-center">{errors.root.message}</p>
          )}

          <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
            {isLoading ? tCommon('loading') : t('signIn')}
          </Button>

          <div className="text-center text-sm">
            <span className="text-muted-foreground">{t('noAccount')} </span>
            <Link href="/register-options" className="font-medium text-primary hover:underline">
              {t('signUp')}
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
