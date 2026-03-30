import { RegisterForm } from '@/components/auth/register-form';

interface RegisterPageProps {
  params: {
    locale: string;
  };
}

export default function RegisterPage({ params }: RegisterPageProps) {
  return <RegisterForm locale={params.locale} />;
}