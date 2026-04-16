"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { getMyCertificates, downloadCertificatePdf } from "@/lib/api";
import type { CertificateListItem } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Award, Download, Loader2, Share2, Copy, Check } from "lucide-react";

interface Props {
  locale: string;
}

export function MyCertificates({ locale }: Props) {
  const t = useTranslations("Certificates");

  const { data: certificates, isLoading } = useQuery({
    queryKey: ["my-certificates"],
    queryFn: getMyCertificates,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      {!certificates?.length ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Award className="mb-4 h-12 w-12 text-amber-400" />
            <h3 className="text-lg font-semibold">{t("empty")}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{t("emptySubtitle")}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {certificates.map((cert) => (
            <CertificateCard key={cert.id} cert={cert} locale={locale} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function CertificateCard({
  cert,
  locale,
  t,
}: {
  cert: CertificateListItem;
  locale: string;
  t: ReturnType<typeof useTranslations>;
}) {
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);

  const courseTitle = locale === "fr" ? cert.course_title_fr : cert.course_title_en;
  const verifyUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/${locale}/verify/${cert.verification_code}`;

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const blob = await downloadCertificatePdf(cert.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `certificate-${cert.verification_code}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silent fail
    } finally {
      setDownloading(false);
    }
  };

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(verifyUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card className="border-2 border-amber-500/30 transition-colors hover:border-amber-500/60">
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-semibold">{courseTitle}</h3>
            <p className="text-sm text-muted-foreground">
              {t("completedOn")}{" "}
              {new Date(cert.completed_at).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US")}
            </p>
          </div>
          <Badge
            className={
              cert.average_score >= 90
                ? "bg-green-50 text-green-700 border-green-200"
                : "bg-teal-50 text-teal-700 border-teal-200"
            }
          >
            {cert.average_score.toFixed(0)}%
          </Badge>
        </div>

        <p className="font-mono text-xs text-muted-foreground">{cert.verification_code}</p>

        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleDownload} disabled={downloading}>
            {downloading ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="mr-1.5 h-3.5 w-3.5" />
            )}
            {downloading ? t("downloading") : t("download")}
          </Button>
          <Button size="sm" variant="ghost" onClick={handleCopyLink}>
            {copied ? (
              <Check className="mr-1.5 h-3.5 w-3.5 text-green-600" />
            ) : (
              <Copy className="mr-1.5 h-3.5 w-3.5" />
            )}
            {copied ? t("linkCopied") : t("copyLink")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
