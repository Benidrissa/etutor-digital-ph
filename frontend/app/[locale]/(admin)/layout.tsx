import { getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { Shield } from 'lucide-react';

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations('Admin');
  return (
    <div className="min-h-dvh bg-stone-50">
      <header className="border-b border-stone-200 bg-white px-4 py-3">
        <div className="container mx-auto max-w-6xl flex items-center gap-3">
          <Shield className="w-5 h-5 text-amber-600" />
          <Link href="/admin/syllabus" className="text-sm font-semibold text-stone-900 hover:text-teal-700 transition-colors">
            {t('title')}
          </Link>
        </div>
      </header>
      <main className="container mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
