import { TOTPLoginForm } from '@/components/auth/totp-login-form';

interface LoginPageProps {
  params: {
    locale: string;
  };
}

export default function LoginPage({ params }: LoginPageProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <TOTPLoginForm locale={params.locale} />
    </div>
  );
}
