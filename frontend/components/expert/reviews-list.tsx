"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, AlertCircle, MessageSquare } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StarRating } from "@/components/marketplace/star-rating";
import { apiFetch } from "@/lib/api";

interface Review {
  id: string;
  rating: number;
  comment: string | null;
  user_name: string;
  created_at: string;
}

interface ReviewsResponse {
  average_rating: number;
  total_reviews: number;
  reviews: Review[];
  page: number;
  page_size: number;
}

function useCourseReviews(courseId: string, page: number) {
  return useQuery<ReviewsResponse>({
    queryKey: ["expert", "courses", courseId, "reviews", page],
    queryFn: () =>
      apiFetch<ReviewsResponse>(
        `/api/v1/expert/courses/${courseId}/reviews?page=${page}&page_size=10`
      ),
  });
}

function formatDate(dateStr: string, locale: string): string {
  return new Date(dateStr).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

interface ReviewsListProps {
  courseId: string;
  locale: string;
}

export function ReviewsList({ courseId, locale }: ReviewsListProps) {
  const t = useTranslations("ExpertReviews");
  const [page, setPage] = useState(1);

  const { data, isLoading, error, refetch } = useCourseReviews(courseId, page);

  const totalPages = data ? Math.ceil(data.total_reviews / data.page_size) : 1;

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

  if (!data) return null;

  return (
    <div className="space-y-6">
      {data.total_reviews > 0 && (
        <Card className="p-4 flex items-center gap-4">
          <div className="text-center">
            <p className="text-4xl font-bold">{data.average_rating.toFixed(1)}</p>
            <StarRating rating={data.average_rating} size="md" className="mt-1" />
            <p className="text-xs text-muted-foreground mt-1">
              {t("totalReviews", { count: data.total_reviews })}
            </p>
          </div>
        </Card>
      )}

      {!data.reviews || data.reviews.length === 0 ? (
        <div className="py-12 text-center">
          <MessageSquare className="h-12 w-12 text-muted-foreground mx-auto mb-4" aria-hidden="true" />
          <p className="font-medium text-muted-foreground">{t("noReviews")}</p>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-3">
            {data.reviews.map((review) => (
              <Card key={review.id} className="p-4">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{review.user_name}</p>
                      <StarRating rating={review.rating} size="sm" />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {formatDate(review.created_at, locale)}
                    </p>
                  </div>
                  {review.comment && (
                    <p className="text-sm text-muted-foreground">{review.comment}</p>
                  )}
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
