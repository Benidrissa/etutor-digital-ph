"use client";

import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Phone } from "lucide-react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";

interface AdminUser {
  id: string;
  email: string | null;
  name: string;
  preferred_language: string;
  country: string | null;
  professional_role: string | null;
  current_level: number;
  streak_days: number;
  avatar_url: string | null;
  last_active: string;
  created_at: string;
  role: "user" | "expert" | "admin";
  is_active: boolean;
  phone_number: string | null;
  analytics_opt_out: boolean;
}

interface ModuleProgressItem {
  module_id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
  status: string;
  completion_pct: number;
  quiz_score_avg: number | null;
  time_spent_minutes: number;
  last_accessed: string | null;
}

interface QuizAttemptItem {
  id: string;
  quiz_id: string;
  score: number | null;
  time_taken_sec: number | null;
  attempted_at: string;
}

export function UserDetailClient({ userId }: { userId: string }) {
  const t = useTranslations("Admin.userDetail");
  const tRoles = useTranslations("Roles");
  const tUsers = useTranslations("Admin.users");
  const locale = useLocale();
  const router = useRouter();

  const { data: user, isLoading: loadingUser, error: userError } = useQuery<AdminUser>({
    queryKey: ["admin", "users", userId],
    queryFn: () => apiFetch<AdminUser>(`/api/v1/admin/users/${userId}`),
  });

  const { data: progress, isLoading: loadingProgress } = useQuery<ModuleProgressItem[]>({
    queryKey: ["admin", "users", userId, "progress"],
    queryFn: () => apiFetch<ModuleProgressItem[]>(`/api/v1/admin/users/${userId}/progress`),
    enabled: !!user,
  });

  const { data: quizHistory, isLoading: loadingQuiz } = useQuery<QuizAttemptItem[]>({
    queryKey: ["admin", "users", userId, "quiz-history"],
    queryFn: () => apiFetch<QuizAttemptItem[]>(`/api/v1/admin/users/${userId}/quiz-history`),
    enabled: !!user,
  });

  if (loadingUser) {
    return <p className="py-8 text-center text-muted-foreground">{t("loading")}</p>;
  }

  if (userError || !user) {
    return (
      <p className="py-8 text-center text-destructive" role="alert">
        {userError ? t("error") : t("notFound")}
      </p>
    );
  }

  const roleVariant =
    user.role === "admin" ? "destructive" : user.role === "expert" ? "secondary" : "outline";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="min-h-11 min-w-11 gap-2"
          onClick={() => router.push(`/${locale}/admin/users`)}
          aria-label={t("backToList")}
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          <span className="hidden sm:inline">{t("backToList")}</span>
        </Button>
        <h1 className="text-xl font-semibold truncate">{user.name}</h1>
      </div>

      <Card className="p-4 md:p-6">
        <div className="flex items-start gap-4 mb-4">
          {user.avatar_url && (
            <Image
              src={user.avatar_url}
              alt={user.name}
              width={56}
              height={56}
              className="rounded-full object-cover shrink-0"
            />
          )}
          <h2 className="text-base font-semibold">{t("profile")}</h2>
        </div>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          {user.email && (
            <div>
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-medium mt-0.5">{user.email}</dd>
            </div>
          )}
          {user.phone_number && (
            <div>
              <dt className="text-muted-foreground flex items-center gap-1">
                <Phone className="h-3 w-3" aria-hidden="true" />
                {t("phoneNumber")}
              </dt>
              <dd className="font-medium mt-0.5">{user.phone_number}</dd>
            </div>
          )}
          <div>
            <dt className="text-muted-foreground">{tUsers("filterRole")}</dt>
            <dd className="mt-0.5">
              <Badge variant={roleVariant}>{tRoles(user.role)}</Badge>
              {!user.is_active && (
                <Badge variant="destructive" className="ml-2">{tUsers("inactive")}</Badge>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("language")}</dt>
            <dd className="mt-0.5">
              <Badge variant="outline" className="uppercase">{user.preferred_language}</Badge>
            </dd>
          </div>
          {user.country && (
            <div>
              <dt className="text-muted-foreground">{tUsers("filterCountry")}</dt>
              <dd className="font-medium mt-0.5">{user.country}</dd>
            </div>
          )}
          {user.professional_role && (
            <div>
              <dt className="text-muted-foreground">{t("professionalRole")}</dt>
              <dd className="font-medium mt-0.5">{user.professional_role}</dd>
            </div>
          )}
          <div>
            <dt className="text-muted-foreground">{tUsers("filterLevel")}</dt>
            <dd className="font-medium mt-0.5">{tUsers("level", { level: user.current_level })}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{tUsers("streakDays", { days: user.streak_days })}</dt>
            <dd className="font-medium mt-0.5">{user.streak_days}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{tUsers("memberSince")}</dt>
            <dd className="font-medium mt-0.5">
              {new Date(user.created_at).toLocaleDateString(locale)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{tUsers("lastActive")}</dt>
            <dd className="font-medium mt-0.5">
              {new Date(user.last_active).toLocaleDateString(locale)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("analyticsOptOut")}</dt>
            <dd className="mt-0.5">
              <Badge variant={user.analytics_opt_out ? "secondary" : "outline"}>
                {user.analytics_opt_out ? t("yes") : t("no")}
              </Badge>
            </dd>
          </div>
        </dl>
      </Card>

      <Card className="p-4 md:p-6">
        <h2 className="text-base font-semibold mb-4">{t("progress")}</h2>
        {loadingProgress && (
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        )}
        {!loadingProgress && (!progress || progress.length === 0) && (
          <p className="text-sm text-muted-foreground">{t("noProgress")}</p>
        )}
        {progress && progress.length > 0 && (
          <div className="flex flex-col gap-3">
            {progress.map((item) => (
              <div key={item.module_id} className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="font-medium truncate">
                    M{String(item.module_number).padStart(2, "0")} —{" "}
                    {locale === "fr" ? item.title_fr : item.title_en}
                  </span>
                  <span className="text-muted-foreground shrink-0">
                    {t("completionPct", { pct: Math.round(item.completion_pct) })}
                  </span>
                </div>
                <Progress value={item.completion_pct} className="h-2" />
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-4 md:p-6">
        <h2 className="text-base font-semibold mb-4">{t("quizHistory")}</h2>
        {loadingQuiz && (
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        )}
        {!loadingQuiz && (!quizHistory || quizHistory.length === 0) && (
          <p className="text-sm text-muted-foreground">{t("noQuizHistory")}</p>
        )}
        {quizHistory && quizHistory.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="text-left pb-2 pr-4">{t("attemptDate")}</th>
                  <th className="text-left pb-2 pr-4">{t("quizScore")}</th>
                  <th className="text-left pb-2">{t("passed")}</th>
                </tr>
              </thead>
              <tbody>
                {quizHistory.map((attempt) => (
                  <tr key={attempt.id} className="border-b last:border-0">
                    <td className="py-2 pr-4">
                      {new Date(attempt.attempted_at).toLocaleDateString(locale)}
                    </td>
                    <td className="py-2 pr-4">
                      {attempt.score !== null
                        ? t("score", { score: Math.round(attempt.score) })
                        : "—"}
                    </td>
                    <td className="py-2">
                      {attempt.score !== null ? (
                        <Badge variant={attempt.score >= 80 ? "default" : "destructive"}>
                          {attempt.score >= 80 ? t("passed") : t("failed")}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
