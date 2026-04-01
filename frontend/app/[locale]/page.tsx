import { redirect } from '@/i18n/routing';

export default function RootPage({ params }: { params: { locale: string } }) {
  redirect({ href: '/dashboard', locale: params.locale });
}
