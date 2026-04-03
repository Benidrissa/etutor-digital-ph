import { redirect } from '@/i18n/routing';

export default async function RegisterPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  redirect({ href: '/register-options', locale });
}
