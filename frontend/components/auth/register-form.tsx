'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslations } from 'next-intl';
import { z } from 'zod';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { supabase } from '@/lib/supabase';

const createRegistrationSchema = (t: (key: string) => string) => z.object({
  name: z.string().min(1, t('nameRequired')),
  email: z.string().min(1, t('emailRequired')).email(t('emailInvalid')),
  password: z
    .string()
    .min(8, t('passwordRequirements'))
    .regex(/^(?=.*[A-Z])(?=.*\d)/, t('passwordRequirements')),
  confirmPassword: z.string().min(1, t('passwordRequired')),
}).refine((data) => data.password === data.confirmPassword, {
  message: t('passwordsDoNotMatch'),
  path: ['confirmPassword'],
});

type RegistrationForm = z.infer<ReturnType<typeof createRegistrationSchema>>;

interface RegisterFormProps {
  locale: string;
}

export function RegisterForm({ locale }: RegisterFormProps) {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const [isLoading, setIsLoading] = useState(false);
  const [isVerificationSent, setIsVerificationSent] = useState(false);

  const registrationSchema = createRegistrationSchema(t);
  
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<RegistrationForm>({
    resolver: zodResolver(registrationSchema),
  });

  const onSubmit = async (data: RegistrationForm) => {
    setIsLoading(true);
    
    try {
      const { error } = await supabase.auth.signUp({
        email: data.email,
        password: data.password,
        options: {
          data: {
            name: data.name,
          },
          emailRedirectTo: `${window.location.origin}/${locale}/onboarding`,
        },
      });

      if (error) {
        // Handle specific Supabase errors
        if (error.message.includes('duplicate') || error.message.includes('already registered')) {
          setError('email', { message: t('duplicateEmail') });
        } else if (error.message.includes('password') || error.message.includes('weak')) {
          setError('password', { message: t('weakPassword') });
        } else if (error.message.includes('network') || error.message.includes('fetch')) {
          setError('root', { message: t('networkError') });
        } else {
          setError('root', { message: t('registrationFailed') });
        }
      } else {
        setIsVerificationSent(true);
      }
    } catch (error) {
      console.error('Registration error:', error);
      setError('root', { message: t('networkError') });
    } finally {
      setIsLoading(false);
    }
  };

  if (isVerificationSent) {
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
          <CardDescription className="text-green-600">
            {t('emailVerificationSent')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center">
            Please check your email and click the verification link to complete your registration.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
        <CardDescription>{t('register')}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Name Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="name">
              {t('name')}
            </label>
            <input
              {...register('name')}
              id="name"
              type="text"
              autoComplete="name"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder="John Doe"
            />
            {errors.name && (
              <p className="text-sm text-red-600">{errors.name.message}</p>
            )}
          </div>

          {/* Email Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="email">
              {t('email')}
            </label>
            <input
              {...register('email')}
              id="email"
              type="email"
              autoComplete="email"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder="email@example.com"
            />
            {errors.email && (
              <p className="text-sm text-red-600">{errors.email.message}</p>
            )}
          </div>

          {/* Password Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="password">
              {t('password')}
            </label>
            <input
              {...register('password')}
              id="password"
              type="password"
              autoComplete="new-password"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            />
            {errors.password && (
              <p className="text-sm text-red-600">{errors.password.message}</p>
            )}
            <p className="text-xs text-muted-foreground">{t('passwordRequirements')}</p>
          </div>

          {/* Confirm Password Field */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="confirmPassword">
              {t('confirmPassword')}
            </label>
            <input
              {...register('confirmPassword')}
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            />
            {errors.confirmPassword && (
              <p className="text-sm text-red-600">{errors.confirmPassword.message}</p>
            )}
          </div>

          {/* Root Error */}
          {errors.root && (
            <p className="text-sm text-red-600 text-center">{errors.root.message}</p>
          )}

          {/* Submit Button */}
          <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
            {isLoading ? tCommon('loading') : t('signUp')}
          </Button>

          {/* Social Login Divider */}
          <div className="relative my-4">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card px-2 text-muted-foreground">ou</span>
            </div>
          </div>

          {/* Social Login Buttons */}
          <Button 
            type="button" 
            variant="outline" 
            className="w-full min-h-11"
            disabled={isLoading}
          >
            {t('withGoogle')}
          </Button>
          <Button 
            type="button" 
            variant="outline" 
            className="w-full min-h-11"
            disabled={isLoading}
          >
            {t('withLinkedIn')}
          </Button>

          {/* Login Link */}
          <div className="text-center text-sm">
            <span className="text-muted-foreground">{t('alreadyHaveAccount')} </span>
            <Link 
              href={`/${locale}/login`}
              className="font-medium text-primary hover:underline"
            >
              {t('signIn')}
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}