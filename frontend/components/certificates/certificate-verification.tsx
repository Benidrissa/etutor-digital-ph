"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { verifyCertificate } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, XCircle, Loader2, Award } from "lucide-react";

interface Props {
  code: string;
  locale: string;
}

export function CertificateVerification({ code, locale }: Props) {
  const t = useTranslations("Certificates");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["verify-certificate", code],
    queryFn: () => verifyCertificate(code),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError || !data?.valid) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
        <Card className="w-full max-w-md">
          <CardContent className="flex flex-col items-center py-12 text-center">
            <XCircle className="mb-4 h-16 w-16 text-red-500" />
            <h1 className="text-xl font-bold">{t("verificationInvalid")}</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("verificationInvalidSubtitle")}
            </p>
            <p className="mt-4 font-mono text-xs text-muted-foreground">{code}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const courseTitle = locale === "fr" ? data.course_title_fr : data.course_title_en;

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-lg border-2 border-green-500/30">
        <CardContent className="space-y-6 py-8">
          <div className="flex flex-col items-center text-center">
            <CheckCircle className="mb-3 h-16 w-16 text-green-500" />
            <h1 className="text-xl font-bold text-green-700">{t("verificationValid")}</h1>
          </div>

          <div className="space-y-4">
            {data.learner_name && (
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  {t("awardedTo")}
                </p>
                <p className="text-lg font-semibold">{data.learner_name}</p>
              </div>
            )}

            {courseTitle && (
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  {t("forCompleting")}
                </p>
                <p className="text-lg font-semibold">{courseTitle}</p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              {data.average_score != null && (
                <div>
                  <p className="text-xs font-medium uppercase text-muted-foreground">
                    {t("averageScore")}
                  </p>
                  <Badge
                    className={
                      data.average_score >= 90
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-teal-50 text-teal-700 border-teal-200"
                    }
                  >
                    {data.average_score.toFixed(0)}%
                  </Badge>
                </div>
              )}

              {data.completion_date && (
                <div>
                  <p className="text-xs font-medium uppercase text-muted-foreground">
                    {t("completedOn")}
                  </p>
                  <p className="text-sm font-medium">
                    {new Date(data.completion_date).toLocaleDateString(
                      locale === "fr" ? "fr-FR" : "en-US"
                    )}
                  </p>
                </div>
              )}
            </div>

            {data.organization_name && (
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  {t("organization")}
                </p>
                <p className="text-sm">{data.organization_name}</p>
              </div>
            )}

            {data.signatory_name && (
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  {t("signedBy")}
                </p>
                <p className="text-sm">{data.signatory_name}</p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-center gap-2 border-t pt-4 text-xs text-muted-foreground">
            <Award className="h-4 w-4" />
            <span>{code}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
