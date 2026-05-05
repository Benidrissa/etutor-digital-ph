import { redirect } from '@/i18n/routing';

// `/modules/{moduleId}/units` is not a real user-facing route — only
// `/modules/{moduleId}/units/{unit}` is. Without a `page.tsx` here,
// Next.js's RSC prefetcher 404s when it walks up the route tree
// during navigation, polluting the console and Sentry. Redirecting
// to the parent module overview turns that into a 200 + clean
// fallback. See sweep finding F-023 in #2132.
export default async function UnitsIndexRedirectPage({
  params,
}: {
  params: Promise<{ locale: string; moduleId: string }>;
}) {
  const { locale, moduleId } = await params;
  redirect({ href: `/modules/${moduleId}`, locale });
}
