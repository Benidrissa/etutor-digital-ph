import { CertificateVerification } from "@/components/certificates/certificate-verification";
import type { Metadata } from "next";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ code: string }>;
}): Promise<Metadata> {
  const { code } = await params;
  return {
    title: `Certificate Verification — ${code}`,
    openGraph: {
      title: "Certificate Verification — Sira",
      description: "Verify a course completion certificate",
      type: "website",
    },
  };
}

export default async function VerifyPage({
  params,
}: {
  params: Promise<{ locale: string; code: string }>;
}) {
  const { locale, code } = await params;
  return <CertificateVerification code={code} locale={locale} />;
}
