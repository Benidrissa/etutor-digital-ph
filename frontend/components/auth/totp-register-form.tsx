'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslations } from 'next-intl';
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
import { authClient, RegisterResponse, AuthError } from '@/lib/auth';

// Step 1: Registration form schema
const createRegistrationSchema = (t: (key: string) => string) => z.object({
  name: z.string().min(2, t('nameRequired')).max(100, t('nameTooLong')),
  email: z.string().min(1, t('emailRequired')).email(t('emailInvalid')),
  preferred_language: z.enum(['fr', 'en'], { required_error: t('languageRequired') }),
  country: z.string().optional(),
  professional_role: z.string().optional(),
});

// Step 2: TOTP verification schema
const createTOTPSchema = (t: (key: string) => string) => z.object({
  totp_code: z
    .string()
    .length(6, t('totpInvalid'))
    .regex(/^\d{6}$/, t('totpInvalid')),
});

type RegistrationForm = z.infer<ReturnType<typeof createRegistrationSchema>>;
type TOTPForm = z.infer<ReturnType<typeof createTOTPSchema>>;

interface TOTPRegisterFormProps {
  locale: string;
}

export function TOTPRegisterForm({ locale }: TOTPRegisterFormProps) {
  const t = useTranslations('Auth');
  const tCommon = useTranslations('Common');
  const router = useRouter();
  
  const [step, setStep] = useState<'register' | 'totp'>('register');
  const [isLoading, setIsLoading] = useState(false);
  const [registerResponse, setRegisterResponse] = useState<RegisterResponse | null>(null);
  const [showBackupCodes, setShowBackupCodes] = useState(false);

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

  // TOTP verification form
  const totpSchema = createTOTPSchema(t);
  const {
    register: registerTOTP,
    handleSubmit: handleTOTPSubmit,
    formState: { errors: totpErrors },
    setError: setTOTPError,
    reset: resetTOTP,
  } = useForm<TOTPForm>({
    resolver: zodResolver(totpSchema),
  });

  const onRegistrationSubmit = async (data: RegistrationForm) => {
    setIsLoading(true);
    
    try {
      const response = await authClient.register(data);
      setRegisterResponse(response);
      setStep('totp');
    } catch (error) {
      console.error('Registration error:', error);
      
      if (error instanceof AuthError) {
        if (error.message.includes('already exists')) {
          setError('email', { message: t('duplicateEmail') });
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

  const onTOTPSubmit = async (data: TOTPForm) => {
    if (!registerResponse) return;
    
    setIsLoading(true);
    
    try {
      await authClient.verifyTOTP(
        registerResponse.user_id,
        data.totp_code
      );
      
      // Registration complete - redirect to onboarding
      router.push(`/${locale}/onboarding`);
    } catch (error) {
      console.error('TOTP verification error:', error);
      
      if (error instanceof AuthError) {
        setTOTPError('totp_code', { message: t('totpInvalid') });
      } else {
        setTOTPError('root', { message: t('verificationFailed') });
      }
    } finally {
      setIsLoading(false);
    }
  };

  const retryRegistration = () => {
    setStep('register');
    setRegisterResponse(null);
    setShowBackupCodes(false);
    resetTOTP();
  };

  // Step 1: Registration Form
  if (step === 'register') {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
          <CardDescription>{t('register')}</CardDescription>
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
              {isLoading ? tCommon('loading') : t('continueToMFA')}
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

  // Step 2: TOTP Setup
  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{t('setupAuthenticator')}</CardTitle>
        <CardDescription>{t('setupAuthenticatorDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* QR Code */}
        {registerResponse && (
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
            <div className="space-y-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowBackupCodes(!showBackupCodes)}
                className="w-full"
              >
                {showBackupCodes ? t('hideBackupCodes') : t('showBackupCodes')}
              </Button>
              
              {showBackupCodes && (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-sm font-medium text-amber-800 mb-2">
                    {t('backupCodesWarning')}
                  </p>
                  <div className="grid grid-cols-2 gap-1 text-xs font-mono">
                    {registerResponse.backup_codes.map((code, index) => (
                      <div key={index} className="bg-white p-1 rounded border">
                        {code}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TOTP Verification Form */}
        <form onSubmit={handleTOTPSubmit(onTOTPSubmit)} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="totp_code">
              {t('enterAuthenticatorCode')}
            </label>
            <input
              {...registerTOTP('totp_code')}
              id="totp_code"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 text-center text-lg tracking-wider"
              placeholder="123456"
            />
            {totpErrors.totp_code && (
              <p className="text-sm text-red-600">{totpErrors.totp_code.message}</p>
            )}
            <p className="text-xs text-muted-foreground text-center">
              {t('totpInstructions')}
            </p>
          </div>

          {/* Root Error */}
          {totpErrors.root && (
            <p className="text-sm text-red-600 text-center">{totpErrors.root.message}</p>
          )}

          {/* Action Buttons */}
          <div className="space-y-2">
            <Button type="submit" className="w-full min-h-11" disabled={isLoading}>
              {isLoading ? tCommon('loading') : t('completeRegistration')}
            </Button>
            
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={retryRegistration}
              disabled={isLoading}
            >
              {t('backToRegistration')}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}