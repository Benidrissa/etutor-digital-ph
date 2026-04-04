import { getTranslations } from "next-intl/server";
import { getLocale } from "next-intl/server";
import { ReviewsList } from "@/components/expert/reviews-list";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations("ExpertReviews");
  return {
    title: t("pageTitle"),
  };
}

export default async function CourseReviewsPage({ params }: PageProps) {
  const { id } = await params;
  const t = await getTranslations("ExpertReviews");
  const locale = await getLocale();

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t("pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("pageDescription")}</p>
      </div>
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <ReviewsList courseId={id} locale={locale} />
      </div>
    </div>
  );
}
