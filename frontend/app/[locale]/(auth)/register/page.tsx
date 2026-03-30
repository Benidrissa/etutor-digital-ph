import { TOTPRegisterForm } from '@/components/auth/totp-register-form';

interface RegisterPageProps {
  params: {
    locale: string;
  };
}

export default function RegisterPage({ params }: RegisterPageProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <TOTPRegisterForm locale={params.locale} />
    </div>
  );
}