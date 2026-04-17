import { CertificateTemplateEditor } from "@/components/certificates/certificate-template-editor";
import { apiFetch } from "@/lib/api";

export default async function CertificateTemplatePage({
  params,
}: {
  params: Promise<{ locale: string; courseSlug: string }>;
}) {
  const { locale, courseSlug } = await params;
  const course = await apiFetch<{ id: string }>(`/api/v1/courses/${courseSlug}`);
  return <CertificateTemplateEditor courseId={course.id} locale={locale} />;
}
