import { getTranslations } from 'next-intl/server';
import { buttonVariants } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Link } from '@/i18n/routing';
import { cn } from '@/lib/utils';

interface Props {
  params: {
    locale: string;
  };
}

export default async function RegisterOptionsPage({ params }: Props) {
  const t = await getTranslations('Auth');
  const tCommon = await getTranslations('Common');
  
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{tCommon('appName')}</CardTitle>
          <CardDescription>{t('chooseVerificationMethod')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Email OTP Option */}
          <div className="space-y-4">
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                  <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 4.45a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-semibold">{t('emailVerification')}</h3>
                  <p className="text-sm text-muted-foreground">{t('emailVerificationDesc')}</p>
                </div>
              </div>
              <Link 
                href={`/${params.locale}/register-email-otp`}
                className={cn(buttonVariants({ variant: "default" }), "w-full min-h-11")}
              >
                {t('continueWithEmail')}
              </Link>
              <div className="text-xs text-muted-foreground">
                {t('emailVerificationBenefits')}
              </div>
            </div>

            {/* Authenticator App Option */}
            <div className="space-y-4">
              <div className="rounded-lg border p-4 space-y-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
                    <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.031 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-semibold">{t('authenticatorApp')}</h3>
                    <p className="text-sm text-muted-foreground">{t('authenticatorAppDesc')}</p>
                  </div>
                </div>
                <Link 
                  href={`/${params.locale}/register-totp`}
                  className={cn(buttonVariants({ variant: "outline" }), "w-full min-h-11")}
                >
                  {t('continueWithAuthenticator')}
                </Link>
                <div className="text-xs text-muted-foreground">
                  {t('authenticatorAppBenefits')}
                </div>
              </div>
            </div>

            {/* Login Link */}
            <div className="text-center text-sm border-t pt-4">
              <span className="text-muted-foreground">{t('alreadyHaveAccount')} </span>
              <Link 
                href={`/${params.locale}/login`}
                className="font-medium text-primary hover:underline"
              >
                {t('signIn')}
              </Link>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}