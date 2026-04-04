"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertCircle,
  Users,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

interface Learner {
  id: string;
  name: string;
  email: string;
  enrolled_at: string;
  progress_pct: number;
  last_active: string | null;
}

interface LearnersResponse {
  learners: Learner[];
  total: number;
  page: number;
  page_size: number;
}

function useCourseLearners(courseId: string, page: number, search: string) {
  return useQuery<LearnersResponse>({
    queryKey: ["expert", "courses", courseId, "learners", page, search],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), page_size: "20" });
      if (search) params.set("search", search);
      return apiFetch<LearnersResponse>(
        `/api/v1/expert/courses/${courseId}/learners?${params.toString()}`
      );
    },
  });
}

function formatDate(dateStr: string | null, locale: string): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

interface LearnerTableProps {
  courseId: string;
  locale: string;
}

export function LearnerTable({ courseId, locale }: LearnerTableProps) {
  const t = useTranslations("ExpertLearners");
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const { data, isLoading, error, refetch } = useCourseLearners(courseId, page, search);

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" aria-label={t("loading")} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">{t("errorLoading")}</p>
        <Button variant="outline" onClick={() => refetch()}>
          {t("retry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            placeholder={t("searchPlaceholder")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9 min-h-11"
            aria-label={t("searchPlaceholder")}
          />
        </div>
        <Button type="submit" variant="outline" className="min-h-11">
          {t("search")}
        </Button>
      </form>

      {!data?.learners || data.learners.length === 0 ? (
        <div className="py-12 text-center">
          <Users className="h-12 w-12 text-muted-foreground mx-auto mb-4" aria-hidden="true" />
          <p className="font-medium text-muted-foreground">{t("noLearners")}</p>
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {t("learnerCount", { count: data.total })}
          </p>

          <div className="hidden md:block overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/50 border-b">
                  <th className="text-left px-4 py-3 font-medium">{t("name")}</th>
                  <th className="text-left px-4 py-3 font-medium">{t("email")}</th>
                  <th className="text-left px-4 py-3 font-medium">{t("enrolledDate")}</th>
                  <th className="text-left px-4 py-3 font-medium">{t("progress")}</th>
                  <th className="text-left px-4 py-3 font-medium">{t("lastActive")}</th>
                </tr>
              </thead>
              <tbody>
                {data.learners.map((learner) => (
                  <tr key={learner.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3 font-medium">{learner.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{learner.email}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {formatDate(learner.enrolled_at, locale)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 rounded-full bg-muted max-w-[80px]">
                          <div
                            className="h-1.5 rounded-full bg-primary"
                            style={{ width: `${learner.progress_pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {Math.round(learner.progress_pct)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {formatDate(learner.last_active, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-3 md:hidden">
            {data.learners.map((learner) => (
              <Card key={learner.id} className="p-4">
                <div className="flex flex-col gap-1">
                  <p className="font-medium text-sm">{learner.name}</p>
                  <p className="text-xs text-muted-foreground">{learner.email}</p>
                  <div className="flex items-center gap-3 mt-2 flex-wrap text-xs text-muted-foreground">
                    <span>{t("enrolledDate")}: {formatDate(learner.enrolled_at, locale)}</span>
                    <span>{t("lastActive")}: {formatDate(learner.last_active, locale)}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <div className="flex-1 h-1.5 rounded-full bg-muted">
                      <div
                        className="h-1.5 rounded-full bg-primary"
                        style={{ width: `${learner.progress_pct}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {Math.round(learner.progress_pct)}%
                    </span>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between gap-3">
              <Button
                variant="outline"
                size="sm"
                className="min-h-11 gap-1"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                aria-label={t("previousPage")}
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                {t("previous")}
              </Button>
              <span className="text-sm text-muted-foreground">
                {t("pageOf", { page, total: totalPages })}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="min-h-11 gap-1"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                aria-label={t("nextPage")}
              >
                {t("next")}
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
