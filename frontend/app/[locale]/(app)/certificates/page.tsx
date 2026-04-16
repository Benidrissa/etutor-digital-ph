import { MyCertificates } from "@/components/certificates/my-certificates";

export default async function CertificatesPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  return <MyCertificates locale={locale} />;
}
