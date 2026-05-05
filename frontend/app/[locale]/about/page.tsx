'use client';

import { useTranslations } from 'next-intl';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import {
  BookOpen,
  Upload,
  Brain,
  WifiOff,
  MessageCircle,
  BarChart3,
  ShoppingBag,
  Route,
  Languages,
  Smartphone,
  Globe,
  GraduationCap,
  Briefcase,
  Building2,
  ShieldCheck,
  Lock,
  Scale,
  Mail,
  ArrowLeft,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { useSettings } from '@/lib/settings-context';

const FEATURES = [
  { titleKey: 'featureSmartCourseTitle', descKey: 'featureSmartCourseDesc', icon: Upload },
  { titleKey: 'featureTutorTitle', descKey: 'featureTutorDesc', icon: MessageCircle },
  { titleKey: 'featureAdaptiveTitle', descKey: 'featureAdaptiveDesc', icon: BarChart3 },
  { titleKey: 'featureRevisionTitle', descKey: 'featureRevisionDesc', icon: Brain },
  { titleKey: 'featureOfflineTitle', descKey: 'featureOfflineDesc', icon: WifiOff },
  { titleKey: 'featureMarketplaceTitle', descKey: 'featureMarketplaceDesc', icon: ShoppingBag },
  { titleKey: 'featureLearningPathsTitle', descKey: 'featureLearningPathsDesc', icon: Route },
  { titleKey: 'featureBilingualTitle', descKey: 'featureBilingualDesc', icon: Languages },
  { titleKey: 'featurePaymentsTitle', descKey: 'featurePaymentsDesc', icon: Smartphone },
  { titleKey: 'featureMultiDomainTitle', descKey: 'featureMultiDomainDesc', icon: Globe },
] as const;

const AUDIENCE = [
  { titleKey: 'builtForLearnersTitle', descKey: 'builtForLearnersDesc', icon: GraduationCap },
  { titleKey: 'builtForExpertsTitle', descKey: 'builtForExpertsDesc', icon: Briefcase },
  { titleKey: 'builtForOrgsTitle', descKey: 'builtForOrgsDesc', icon: Building2 },
] as const;

const TRUST = [
  { key: 'trustEncryption', icon: Lock },
  { key: 'trustCompliance', icon: Scale },
  { key: 'trustGlobal', icon: ShieldCheck },
] as const;

export default function AboutPage() {
  const t = useTranslations('About');
  const tAuth = useTranslations('Auth');
  const pathname = usePathname();
  const locale = pathname.split('/')[1] || 'fr';
  // When self-registration is disabled, swap the secondary CTA from
  // 'Become an expert' (which routes to /register and dead-ends at /login)
  // to 'I have a code' (which routes to /activate). See #2110.
  const { getSetting } = useSettings();
  const registrationEnabled = getSetting<boolean>('auth-self-registration-enabled', false);

  return (
    <div className="min-h-dvh bg-white">
      {/* Minimal top bar */}
      <header className="sticky top-0 z-10 border-b bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80">
        <div className="container mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <Link href={`/${locale}/courses`} className="flex items-center gap-2 text-sm text-stone-500 hover:text-stone-900 transition-colors">
            <ArrowLeft className="h-4 w-4" />
            <span className="font-semibold text-stone-900 text-lg">Sira</span>
          </Link>
          <div className="flex items-center gap-2">
            <Link href={`/${locale === 'fr' ? 'en' : 'fr'}/about`}>
              <Button variant="ghost" size="sm" className="text-xs">
                {locale === 'fr' ? 'EN' : 'FR'}
              </Button>
            </Link>
            <Link href={`/${locale}/login`}>
              <Button variant="outline" size="sm">
                {locale === 'fr' ? 'Connexion' : 'Sign in'}
              </Button>
            </Link>
          </div>
        </div>
      </header>

      <main className="container mx-auto max-w-5xl px-4">
        {/* Hero */}
        <section className="py-16 md:py-24 text-center">
          <p className="text-sm text-teal-700 font-medium mb-3">{t('heroOrigin')}</p>
          <h1 className="text-4xl md:text-5xl font-bold text-stone-900 mb-4 tracking-tight">
            Sira — {t('heroHeadline')}
          </h1>
          <p className="text-lg md:text-xl text-stone-600 max-w-2xl mx-auto leading-relaxed">
            {t('heroDescription')}
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mt-8">
            <Link href={`/${locale}/courses`}>
              <Button size="lg" className="bg-teal-700 hover:bg-teal-800 text-white px-8">
                <BookOpen className="mr-2 h-5 w-5" />
                {t('ctaBrowse')}
              </Button>
            </Link>
            <Link href={`/${locale}/${registrationEnabled ? 'register' : 'activate'}`}>
              <Button size="lg" variant="outline" className="px-8">
                {registrationEnabled ? t('ctaExpert') : tAuth('invitationOnlyHaveCode')}
              </Button>
            </Link>
          </div>
        </section>

        <Separator />

        {/* The Problem */}
        <section className="py-16">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-8 text-center">
            {t('problemTitle')}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 max-w-3xl mx-auto">
            {(['problem1', 'problem2', 'problem3', 'problem4'] as const).map((key) => (
              <Card key={key} className="p-5 border-stone-200">
                <p className="text-stone-700 text-sm leading-relaxed">{t(key)}</p>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* How It Works */}
        <section className="py-16">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-10 text-center">
            {t('howTitle')}
          </h2>
          <div className="grid gap-8 md:grid-cols-3">
            {[
              { step: '1', titleKey: 'howStep1Title', descKey: 'howStep1Desc', icon: Upload },
              { step: '2', titleKey: 'howStep2Title', descKey: 'howStep2Desc', icon: Brain },
              { step: '3', titleKey: 'howStep3Title', descKey: 'howStep3Desc', icon: WifiOff },
            ].map(({ step, titleKey, descKey, icon: Icon }) => (
              <div key={step} className="text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-teal-50 text-teal-700">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-semibold text-stone-900 mb-2">
                  <span className="text-teal-700 mr-1">{step}.</span>
                  {t(titleKey)}
                </h3>
                <p className="text-stone-600 text-sm leading-relaxed">{t(descKey)}</p>
              </div>
            ))}
          </div>
        </section>

        <Separator />

        {/* Features Grid */}
        <section className="py-16">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-10 text-center">
            {t('featuresTitle')}
          </h2>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ titleKey, descKey, icon: Icon }) => (
              <Card key={titleKey} className="p-5 border-stone-200 hover:border-teal-200 transition-colors">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-stone-900 text-sm mb-1">{t(titleKey)}</h3>
                    <p className="text-stone-500 text-xs leading-relaxed">{t(descKey)}</p>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* Built For */}
        <section className="py-16">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-10 text-center">
            {t('builtForTitle')}
          </h2>
          <div className="grid gap-6 md:grid-cols-3">
            {AUDIENCE.map(({ titleKey, descKey, icon: Icon }) => (
              <div key={titleKey} className="text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-50 text-amber-700">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-semibold text-stone-900 mb-2">{t(titleKey)}</h3>
                <p className="text-stone-600 text-sm leading-relaxed">{t(descKey)}</p>
              </div>
            ))}
          </div>
        </section>

        <Separator />

        {/* Trust & Compliance */}
        <section className="py-16">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-8 text-center">
            {t('trustTitle')}
          </h2>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-6 max-w-3xl mx-auto">
            {TRUST.map(({ key, icon: Icon }) => (
              <div key={key} className="flex items-center gap-3 text-center sm:text-left">
                <Icon className="h-5 w-5 shrink-0 text-teal-700" />
                <p className="text-stone-600 text-sm">{t(key)}</p>
              </div>
            ))}
          </div>
        </section>

        <Separator />

        {/* Contact */}
        <section className="py-16 text-center">
          <h2 className="text-2xl md:text-3xl font-bold text-stone-900 mb-3">
            {t('contactTitle')}
          </h2>
          <p className="text-stone-600 text-sm mb-4">{t('contactCta')}</p>
          <a
            href={`mailto:${t('contactEmail')}`}
            className="inline-flex items-center gap-2 text-teal-700 hover:text-teal-900 font-medium transition-colors"
          >
            <Mail className="h-5 w-5" />
            {t('contactEmail')}
          </a>
        </section>

        {/* Final CTA */}
        <section className="py-12 text-center">
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href={`/${locale}/courses`}>
              <Button size="lg" className="bg-teal-700 hover:bg-teal-800 text-white px-8">
                <BookOpen className="mr-2 h-5 w-5" />
                {t('ctaBrowse')}
              </Button>
            </Link>
            <Link href={`/${locale}/${registrationEnabled ? 'register' : 'activate'}`}>
              <Button size="lg" variant="outline" className="px-8">
                {registrationEnabled ? t('ctaExpert') : tAuth('invitationOnlyHaveCode')}
              </Button>
            </Link>
          </div>
        </section>
      </main>

      {/* Minimal footer */}
      <footer className="border-t py-8 text-center text-xs text-stone-400">
        <p>&copy; {new Date().getFullYear()} Sira. {locale === 'fr' ? 'Tous droits réservés.' : 'All rights reserved.'}</p>
      </footer>
    </div>
  );
}
