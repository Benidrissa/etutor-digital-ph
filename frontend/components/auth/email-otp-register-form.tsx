'use client';

import { useState, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
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
import { OTPInput, OTPInputRef } from './otp-input';
import { authClient, RegisterEmailOTPResponse, AuthError } from '@/lib/auth';

// Step 1: Registration form schema
const createRegistrationSchema = (t: (key: string) => string) => z.object({
  name: z.string().min(2, t('nameRequired')).max(100, t('nameTooLong')),
  email: z.string().min(1, t('emailRequired')).email(t('emailInvalid')),
  preferred_language: z.enum(['fr', 'en'], { message: t('languageRequired') }),
  country: z.string().optional(),
  professional_role: z.string().optional(),
});

// Step 2: OTP verification schema
const createOTPSchema = (t: (key: string) => string) => z.object({
  otp_code: z
    .string()
    .length(6, t('otpInvalid'))
    .regex(/^\d{6}$/, t('otpInvalid')),
});

type RegistrationForm = z.infer<ReturnType<typeof createRegistrationSchema>>;
type OTPForm = z.infer<ReturnType<typeof createOTPSchema>>;

export function EmailOTPRegisterForm() {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const router = useRouter();
  const locale = useLocale();
  
  const [step, setStep] = useState<'register' | 'otp'>('register');
  const [isLoading, setIsLoading] = useState(false);
  const [registerResponse, setRegisterResponse] = useState<RegisterEmailOTPResponse | null>(null);
  const [expiryTime, setExpiryTime] = useState<number | null>(null);
  const [remainingAttempts, setRemainingAttempts] = useState<number>(5);
  
  const otpInputRef = useRef<OTPInputRef>(null);

  // Registration form
  const registrationSchema = createRegistrationSchema(t);
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<RegistrationForm>({
    resolver: zodResolver(registrationSchema),
    defaultValues: {
      preferred_language: locale as 'fr' | 'en',
    },
  });

  // OTP verification form
  const otpSchema = createOTPSchema(t);
  const {
    handleSubmit: handleOTPSubmit,
    setValue: setOTPValue,
    setError: setOTPError,
    clearErrors: clearOTPErrors,
    formState: { errors: otpErrors },
  } = useForm<OTPForm>({
    resolver: zodResolver(otpSchema),
  });

  const onRegistrationSubmit = async (data: RegistrationForm) => {
    setIsLoading(true);
    
    try {
      const response = await authClient.registerEmailOTP(data);
      setRegisterResponse(response);
      
      // Set expiry countdown
      const expiryTimestamp = Date.now() + (response.expires_in_seconds * 1000);
      setExpiryTime(expiryTimestamp);
      
      setStep('otp');
    } catch (error) {
      console.error('Registration error:', error);
      
      if (error instanceof AuthError) {
        if (error.message.includes('already exists')) {
          setError('email', { message: t('duplicateEmail') });
        } else if (error.message.includes('rate limit') || error.message.includes('Too many')) {
          setError('root', { message: t('rateLimitExceeded') });
        } else {
          setError('root', { message: error.message });
        }
      } else {
        setError('root', { message: t('registrationFailed') });
      }
    } finally {
      setIsLoading(false);
    }
  };

  const onOTPSubmit = async (data: OTPForm) => {
    if (!registerResponse) return;
    
    setIsLoading(true);
    clearOTPErrors();
    
    try {
      await authClient.verifyEmailOTP(
        registerResponse.otp_id,
        data.otp_code
      );
      
      // Registration complete - redirect to onboarding
      router.push(`/${locale}/onboarding`);
    } catch (error) {
      console.error('OTP verification error:', error);
      
      if (error instanceof AuthError) {
        if (error.message.includes('expired')) {
          setOTPError('root', { message: t('otpExpired') });
        } else if (error.message.includes('attempts')) {
          const match = error.message.match(/(\d+) attempts remaining/);
          if (match) {
            setRemainingAttempts(parseInt(match[1]));
          }
          setOTPError('otp_code', { message: error.message });
          otpInputRef.current?.clear();
        } else {
          setOTPError('otp_code', { message: t('otpInvalid') });
          otpInputRef.current?.clear();
        }
      } else {
        setOTPError('root', { message: t('verificationFailed') });
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleOTPChange = (value: string) => {
    setOTPValue('otp_code', value);
    if (otpErrors.otp_code || otpErrors.root) {
      clearOTPErrors();
    }
  };

  const handleOTPComplete = (value: string) => {
    handleOTPSubmit({ otp_code: value });
  };

  const retryRegistration = () => {
    setStep('register');
    setRegisterResponse(null);
    setExpiryTime(null);
    setRemainingAttempts(5);
    clearOTPErrors();
  };

  const resendOTP = async () => {
    if (!registerResponse) return;
    
    setIsLoading(true);
    try {
      const data = {
        name: registerResponse.name,
        email: registerResponse.email,
        preferred_language: locale,
      };
      
      const response = await authClient.registerEmailOTP(data);
      setRegisterResponse(response);
      
      // Reset expiry countdown
      const expiryTimestamp = Date.now() + (response.expires_in_seconds * 1000);
      setExpiryTime(expiryTimestamp);
      setRemainingAttempts(5);
      
      otpInputRef.current?.clear();
      clearOTPErrors();
    } catch (error) {
      console.error('Resend OTP error:', error);
      if (error instanceof AuthError) {
        setOTPError('root', { message: error.message });
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Format expiry countdown
  const formatTimeRemaining = (expiryTimestamp: number): string => {
    const remaining = Math.max(0, expiryTimestamp - Date.now());
    const minutes = Math.floor(remaining / 60000);
    const seconds = Math.floor((remaining % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  // Step 1: Registration Form
  if (step === 'register') {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
          <CardDescription>{t('registerWithEmail')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onRegistrationSubmit)} className="space-y-4">
            {/* Name Field */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="name">
                {t('name')} *
              </label>
              <input
                {...register('name')}
                id="name"
                type="text"
                autoComplete="name"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder={t('namePlaceholder')}
              />
              {errors.name && (
                <p className="text-sm text-red-600">{errors.name.message}</p>
              )}
            </div>

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

            {/* Language Selection */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="language">
                {t('preferredLanguage')} *
              </label>
              <select
                {...register('preferred_language')}
                id="language"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="fr">Français</option>
                <option value="en">English</option>
              </select>
              {errors.preferred_language && (
                <p className="text-sm text-red-600">{errors.preferred_language.message}</p>
              )}
            </div>

            {/* Country (Optional) */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="country">
                {t('country')}
              </label>
              <select
                {...register('country')}
                id="country"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="">{t('selectCountry')}</option>
                <option value="SN">Sénégal</option>
                <option value="GH">Ghana</option>
                <option value="NG">Nigeria</option>
                <option value="CI">Côte d&apos;Ivoire</option>
                <option value="BF">Burkina Faso</option>
                <option value="ML">Mali</option>
                <option value="NE">Niger</option>
                <option value="GN">Guinée</option>
                <option value="SL">Sierra Leone</option>
                <option value="LR">Liberia</option>
                <option value="GW">Guinée-Bissau</option>
                <option value="CV">Cap-Vert</option>
                <option value="GM">Gambie</option>
                <option value="TG">Togo</option>
                <option value="BJ">Bénin</option>
              </select>
              {errors.country && (
                <p className="text-sm text-red-600">{errors.country.message}</p>
              )}
            </div>

            {/* Professional Role (Optional) */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="role">
                {t('professionalRole')}
              </label>
              <input
                {...register('professional_role')}
                id="role"
                type="text"
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder={t('rolePlaceholder')}
              />
              {errors.professional_role && (
                <p className="text-sm text-red-600">{errors.professional_role.message}</p>
              )}
            </div>

            {/* Root Error */}
            {errors.root && (
              <p className="text-sm text-red-600 text-center">{errors.root.message}</p>
            )}

            {/* Submit Button */}
            <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
              {isLoading ? tCommon('loading') : t('sendVerificationCode')}
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

            {/* TOTP Option */}
            <div className="text-center text-sm border-t pt-4">
              <span className="text-muted-foreground">{t('preferAuthenticatorApp')} </span>
              <Link 
                href={`/${locale}/register`}
                className="font-medium text-primary hover:underline"
              >
                {t('useAuthenticatorApp')}
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    );
  }

  // Step 2: OTP Verification
  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{t('enterVerificationCode')}</CardTitle>
        <CardDescription>
          {t('verificationCodeSent')} {registerResponse?.email}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form onSubmit={handleOTPSubmit(onOTPSubmit)} className="space-y-4">
          {/* OTP Input */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-center block">
              {t('enterVerificationCode')}
            </label>
            <OTPInput
              ref={otpInputRef}
              length={6}
              onChange={handleOTPChange}
              onComplete={handleOTPComplete}
              disabled={isLoading}
              autoFocus
              error={!!otpErrors.otp_code}
              className="justify-center"
            />
            {otpErrors.otp_code && (
              <p className="text-sm text-red-600 text-center">{otpErrors.otp_code.message}</p>
            )}
          </div>

          {/* Expiry Timer */}
          {expiryTime && (
            <div className="text-center text-sm text-muted-foreground">
              {t('codeExpiresIn')} {formatTimeRemaining(expiryTime)}
            </div>
          )}

          {/* Remaining Attempts */}
          {remainingAttempts < 5 && remainingAttempts > 0 && (
            <div className="text-center text-sm text-amber-600">
              {t('attemptsRemaining', { count: remainingAttempts })}
            </div>
          )}

          {/* Root Error */}
          {otpErrors.root && (
            <p className="text-sm text-red-600 text-center">{otpErrors.root.message}</p>
          )}

          {/* Action Buttons */}
          <div className="space-y-2">
            <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
              {isLoading ? tCommon('loading') : t('completeRegistration')}
            </Button>
            
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={resendOTP}
                disabled={isLoading}
              >
                {t('resendCode')}
              </Button>
              
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={retryRegistration}
                disabled={isLoading}
              >
                {t('backToRegistration')}
              </Button>
            </div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}