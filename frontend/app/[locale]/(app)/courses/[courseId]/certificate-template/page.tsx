import { CertificateTemplateEditor } from "@/components/certificates/certificate-template-editor";

export default async function CertificateTemplatePage({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  const { locale, courseId } = await params;
  return <CertificateTemplateEditor courseId={courseId} locale={locale} />;
}
