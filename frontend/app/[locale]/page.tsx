import { redirect } from "@/i18n/routing";

interface LocaleRootProps {
  params: Promise<{
    locale: string;
  }>;
}

export default async function LocaleRoot({ params }: LocaleRootProps) {
  const { locale } = await params;
  redirect({ href: "/dashboard", locale });
}
