import { redirect } from '@/i18n/routing';

interface Props {
  params: {
    locale: string;
  };
}

export default function RegisterPage({ params }: Props) {
  // Redirect to the registration options page where users can choose between TOTP and email OTP
  redirect({ href: '/register-options', locale: params.locale });
}
