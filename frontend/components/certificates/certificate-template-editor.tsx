"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCertificateTemplate, upsertCertificateTemplate } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Loader2, Save, CheckCircle } from "lucide-react";

interface Props {
  courseId: string;
  locale: string;
}

export function CertificateTemplateEditor({ courseId }: Props) {
  const t = useTranslations("Certificates");
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);

  const [form, setForm] = useState({
    title_fr: "",
    title_en: "",
    organization_name: "",
    signatory_name: "",
    signatory_title: "",
    logo_url: "",
    additional_text_fr: "",
    additional_text_en: "",
  });

  const { isLoading } = useQuery({
    queryKey: ["certificate-template", courseId],
    queryFn: () => getCertificateTemplate(courseId),
    retry: false,
    refetchOnWindowFocus: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onSuccess: (data: any) => {
      setForm({
        title_fr: data.title_fr || "",
        title_en: data.title_en || "",
        organization_name: data.organization_name || "",
        signatory_name: data.signatory_name || "",
        signatory_title: data.signatory_title || "",
        logo_url: data.logo_url || "",
        additional_text_fr: data.additional_text_fr || "",
        additional_text_en: data.additional_text_en || "",
      });
    },
  } as Parameters<typeof useQuery>[0]);

  const mutation = useMutation({
    mutationFn: () => upsertCertificateTemplate(courseId, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["certificate-template", courseId] });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  const handleChange = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">{t("templateEditor")}</h1>
        <p className="text-muted-foreground">{t("templateEditorSubtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("templateEditor")}</CardTitle>
          <CardDescription>{t("templateEditorSubtitle")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("titleFr")}</Label>
              <Input
                value={form.title_fr}
                onChange={(e) => handleChange("title_fr", e.target.value)}
                placeholder="Certificat de réussite"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("titleEn")}</Label>
              <Input
                value={form.title_en}
                onChange={(e) => handleChange("title_en", e.target.value)}
                placeholder="Certificate of Completion"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t("organizationName")}</Label>
            <Input
              value={form.organization_name}
              onChange={(e) => handleChange("organization_name", e.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("signatoryName")}</Label>
              <Input
                value={form.signatory_name}
                onChange={(e) => handleChange("signatory_name", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("signatoryTitle")}</Label>
              <Input
                value={form.signatory_title}
                onChange={(e) => handleChange("signatory_title", e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t("logoUrl")}</Label>
            <Input
              value={form.logo_url}
              onChange={(e) => handleChange("logo_url", e.target.value)}
              placeholder="https://..."
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("additionalTextFr")}</Label>
              <Textarea
                value={form.additional_text_fr}
                onChange={(e) => handleChange("additional_text_fr", e.target.value)}
                rows={3}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("additionalTextEn")}</Label>
              <Textarea
                value={form.additional_text_en}
                onChange={(e) => handleChange("additional_text_en", e.target.value)}
                rows={3}
              />
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || !form.title_fr || !form.title_en}
            >
              {mutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {mutation.isPending ? t("saving") : t("saveTemplate")}
            </Button>
            {saved && (
              <span className="flex items-center gap-1 text-sm text-green-600">
                <CheckCircle className="h-4 w-4" />
                {t("templateSaved")}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
