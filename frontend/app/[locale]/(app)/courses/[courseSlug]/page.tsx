"use client";

import { useState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useParams } from "next/navigation";
import { useRouter, Link } from "@/i18n/routing";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Clock,
  BookOpen,
  GraduationCap,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  ArrowLeft,
  ClipboardList,
  AlertTriangle,
  KeyRound,
} from "lucide-react";
import { apiFetch, enrollInCourse } from "@/lib/api";
import { authClient } from "@/lib/auth";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ShareButton } from "@/components/shared/share-button";

interface ModuleUnit {
  id: string;
  unit_number: string;
  title_fr: string | null;
  title_en: string | null;
  order_index: number;
}

interface CourseModule {
  id: string;
  module_number: number;
  title_fr: string | null;
  title_en: string | null;
  description_fr: string | null;
  description_en: string | null;
  level: number;
  estimated_hours: number;
  bloom_level: string | null;
  units: ModuleUnit[];
}

interface PreassessmentStatus {
  enabled: boolean;
  mandatory: boolean;
  completed: boolean;
  skipped: boolean;
  can_retake: boolean;
}

interface CourseDetail {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  course_domain: { value: string; label_fr: string; label_en: string }[];
  course_level: { value: string; label_fr: string; label_en: string }[];
  audience_type: { value: string; label_fr: string; label_en: string }[];
  estimated_hours: number;
  module_count: number;
  cover_image_url: string | null;
  enrolled: boolean;
  syllabus_json: Record<string, unknown> | null;
  modules: CourseModule[];
  preassessment_enabled: boolean;
  preassessment_mandatory: boolean;
}

const LEVEL_COLORS: Record<string, string> = {
  beginner: "bg-green-50 text-green-700 border-green-200",
  intermediate: "bg-blue-50 text-blue-700 border-blue-200",
  advanced: "bg-amber-50 text-amber-700 border-amber-200",
  expert: "bg-red-50 text-red-700 border-red-200",
};

export default function CourseDetailPage() {
  const t = useTranslations("Courses");
  const tDetail = useTranslations("CourseDetail");
  const tBloom = useTranslations("BloomTaxonomy");
  const locale = useLocale() as "fr" | "en";
  const params = useParams();
  const router = useRouter();
  const courseSlug = params.courseSlug as string;

  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrolled, setEnrolled] = useState(false);
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [preassessmentStatus, setPreassessmentStatus] = useState<PreassessmentStatus | null>(null);
  const [unenrollDialogOpen, setUnenrollDialogOpen] = useState(false);
  const [unenrolling, setUnenrolling] = useState(false);
  const [unenrollError, setUnenrollError] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string | undefined>(undefined);

  useEffect(() => {
    const user = authClient.getCurrentUser();
    setUserRole(user?.role);
  }, []);

  useEffect(() => {
    apiFetch<CourseDetail>(`/api/v1/courses/${courseSlug}`)
      .then((data) => {
        setCourse(data);
        setEnrolled(data.enrolled);
        setLoading(false);
        if (data.preassessment_enabled) {
          apiFetch<PreassessmentStatus>(`/api/v1/courses/${data.id}/preassessment/status`)
            .then(setPreassessmentStatus)
            .catch(() => {});
        }
      })
      .catch((err: Error) => {
        const is404 = err.message?.includes("404") || err.message?.includes("not found");
        setError(is404 ? "notFound" : "serverError");
        setLoading(false);
      });
  }, [courseSlug]);

  const toggleModule = (moduleId: string) => {
    setExpandedModules((prev) => {
      const next = new Set(prev);
      if (next.has(moduleId)) {
        next.delete(moduleId);
      } else {
        next.add(moduleId);
      }
      return next;
    });
  };

  const handleEnroll = async () => {
    if (!course) return;
    // Redirect unauthenticated users to login
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) {
      router.push(`/login?redirect=/courses/${courseSlug}`);
      return;
    }
    setEnrolling(true);
    try {
      await enrollInCourse(course.id);
      setEnrolled(true);
    } catch {
      // ignore
    } finally {
      setEnrolling(false);
    }
  };

  const handleUnenroll = async () => {
    if (!course) return;
    setUnenrolling(true);
    setUnenrollError(null);
    try {
      await apiFetch(`/api/v1/courses/${course.id}/unenroll`, { method: "POST" });
      setEnrolled(false);
      setUnenrollDialogOpen(false);
    } catch {
      setUnenrollError(tDetail("unenrollError"));
    } finally {
      setUnenrolling(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="container mx-auto max-w-3xl px-4 py-12 text-center">
        <p className="text-muted-foreground">
          {error === "serverError" ? tDetail("serverError") : tDetail("notFound")}
        </p>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/courses")}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          {tDetail("backToCatalog")}
        </Button>
      </div>
    );
  }

  const title = locale === "fr" ? course.title_fr : course.title_en;
  const description = locale === "fr" ? course.description_fr : course.description_en;

  return (
    <div className="container mx-auto max-w-3xl px-4 py-6 space-y-6 pb-24 md:pb-6">
      {/* Back link */}
      <Link
        href="/courses"
        onClick={(e) => {
          if (window.history.length > 1) {
            e.preventDefault();
            router.back();
          }
        }}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        {tDetail("backToCatalog")}
      </Link>

      {/* Cover */}
      {course.cover_image_url ? (
        <div className="relative h-48 sm:h-64 overflow-hidden rounded-xl bg-teal-50">
          <img src={course.cover_image_url} alt={title} className="w-full h-full object-cover" />
        </div>
      ) : (
        <div className="h-48 sm:h-64 rounded-xl bg-gradient-to-br from-teal-600 to-amber-500 flex items-center justify-center">
          <GraduationCap className="h-20 w-20 text-white opacity-80" />
        </div>
      )}

      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-2">
          <h1 className="text-2xl sm:text-3xl font-bold text-stone-900">{title}</h1>
          <ShareButton
            url={`/${locale}/courses/${course.slug || course.id}`}
            title={title}
            description={description || undefined}
            variant="button"
          />
        </div>
        {description && <p className="text-stone-600 mt-2">{description}</p>}

        {/* Taxonomy badges */}
        <div className="flex flex-wrap gap-1.5 mt-3">
          {course.course_domain?.map((d) => (
            <Badge key={d.value} variant="outline" className="text-xs text-amber-700 bg-amber-50 border-amber-200">
              {locale === "fr" ? d.label_fr : d.label_en}
            </Badge>
          ))}
          {course.course_level?.map((l) => (
            <Badge
              key={l.value}
              variant="outline"
              className={`text-xs ${LEVEL_COLORS[l.value] || "bg-stone-50 text-stone-700 border-stone-200"}`}
            >
              {locale === "fr" ? l.label_fr : l.label_en}
            </Badge>
          ))}
          {course.audience_type?.map((a) => (
            <Badge key={a.value} variant="outline" className="text-xs text-violet-700 bg-violet-50 border-violet-200">
              {locale === "fr" ? a.label_fr : a.label_en}
            </Badge>
          ))}
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 mt-3 text-sm text-stone-500">
          <div className="flex items-center gap-1">
            <Clock className="h-4 w-4" />
            <span>{t("hours", { count: course.estimated_hours })}</span>
          </div>
          <div className="flex items-center gap-1">
            <BookOpen className="h-4 w-4" />
            <span>{t("modules", { count: course.module_count })}</span>
          </div>
        </div>
      </div>

      {/* Pre-assessment banner */}
      {course.preassessment_enabled && preassessmentStatus && !preassessmentStatus.completed && (
        <Card className={`border-2 ${preassessmentStatus.mandatory ? "border-amber-400 bg-amber-50" : "border-teal-300 bg-teal-50"}`}>
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              {preassessmentStatus.mandatory ? (
                <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              ) : (
                <ClipboardList className="h-5 w-5 text-teal-600 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <p className={`font-semibold text-sm ${preassessmentStatus.mandatory ? "text-amber-800" : "text-teal-800"}`}>
                  {preassessmentStatus.mandatory
                    ? tDetail("preassessmentMandatoryTitle")
                    : tDetail("preassessmentTitle")}
                </p>
                <p className={`text-sm mt-0.5 ${preassessmentStatus.mandatory ? "text-amber-700" : "text-teal-700"}`}>
                  {preassessmentStatus.mandatory
                    ? tDetail("preassessmentMandatoryDesc")
                    : tDetail("preassessmentDesc")}
                </p>
              </div>
              <Link href={`/courses/${courseSlug}/placement-test`}>
                <Button
                  size="sm"
                  className={`shrink-0 min-h-11 ${preassessmentStatus.mandatory ? "bg-amber-600 hover:bg-amber-700" : "bg-teal-600 hover:bg-teal-700"}`}
                >
                  {tDetail("preassessmentCta")}
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Syllabus — modules */}
      {course.modules.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">{tDetail("syllabus")}</h2>
          <div className="space-y-2">
            {course.modules.map((mod) => {
              const modTitle = locale === "fr" ? mod.title_fr : mod.title_en;
              const modDesc = locale === "fr" ? mod.description_fr : mod.description_en;
              const isExpanded = expandedModules.has(mod.id);

              return (
                <Card key={mod.id} className="overflow-hidden">
                  <button
                    type="button"
                    onClick={() => toggleModule(mod.id)}
                    className="w-full text-left p-4 flex items-start gap-3 hover:bg-stone-50 transition-colors"
                  >
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                      {mod.module_number}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm text-stone-900 leading-tight">
                        {modTitle}
                      </p>
                      <div className="flex items-center gap-2 mt-1 text-xs text-stone-500">
                        <span>{mod.estimated_hours}h</span>
                        <span>{mod.units.length} {tDetail("units")}</span>
                        {mod.bloom_level && (
                          <Badge variant="outline" className="text-[10px] py-0">
                            {tBloom.has(mod.bloom_level)
                              ? tBloom(mod.bloom_level)
                              : mod.bloom_level}
                          </Badge>
                        )}
                      </div>
                    </div>
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-stone-400 shrink-0 mt-1" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-stone-400 shrink-0 mt-1" />
                    )}
                  </button>

                  {isExpanded && (
                    <CardContent className="pt-0 pb-4 px-4">
                      {modDesc && (
                        <p className="text-sm text-stone-600 mb-3 ml-10">{modDesc}</p>
                      )}
                      {mod.units.length > 0 && (
                        <ul className="space-y-1.5 ml-10">
                          {mod.units.map((unit) => {
                            const unitTitle = locale === "fr" ? unit.title_fr : unit.title_en;
                            return (
                              <li key={unit.id} className="flex items-center gap-2 text-sm text-stone-600">
                                <span className="h-1.5 w-1.5 rounded-full bg-stone-300 shrink-0" />
                                <span className="font-mono text-xs text-stone-400">{unit.unit_number}</span>
                                <span>{unitTitle}</span>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </CardContent>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Sticky enroll CTA on mobile */}
      <div className="fixed bottom-16 left-0 right-0 p-4 bg-background/95 backdrop-blur border-t md:static md:border-0 md:p-0 md:bg-transparent">
        {enrolled ? (
          <div className="flex flex-col items-center gap-2">
            <Button
              className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
              onClick={() => router.push(`/modules?course_id=${course.id}`)}
              disabled={
                course.preassessment_enabled &&
                preassessmentStatus?.mandatory === true &&
                preassessmentStatus?.completed === false
              }
              title={
                course.preassessment_enabled &&
                preassessmentStatus?.mandatory === true &&
                preassessmentStatus?.completed === false
                  ? tDetail("preassessmentRequiredTooltip")
                  : undefined
              }
            >
              <CheckCircle className="mr-2 h-4 w-4" />
              {t("viewModules")}
            </Button>
            <button
              type="button"
              onClick={() => setUnenrollDialogOpen(true)}
              className="text-xs text-destructive hover:underline"
            >
              {tDetail("unenroll")}
            </button>
          </div>
        ) : (
          <Button
            className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
            onClick={handleEnroll}
            disabled={enrolling}
          >
            {enrolling ? t("enrolling") : t("enroll")}
          </Button>
        )}
      </div>

      {(userRole === "expert" || userRole === "admin") && (
        <Link
          href={`/courses/${courseSlug}/codes`}
          className="flex items-center justify-center gap-2 w-full min-h-11 rounded-md border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 text-sm font-medium transition-colors"
        >
          <KeyRound className="h-4 w-4" />
          {t("manageCodes")}
        </Link>
      )}

      <AlertDialog open={unenrollDialogOpen} onOpenChange={setUnenrollDialogOpen}>
        <AlertDialogContent>
          <AlertDialogTitle>{tDetail("unenrollTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{tDetail("unenrollDescription")}</AlertDialogDescription>
          {unenrollError && (
            <p className="text-sm text-destructive mt-2" role="alert">{unenrollError}</p>
          )}
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setUnenrollDialogOpen(false)}>
              {t("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleUnenroll}
              disabled={unenrolling}
              className="bg-destructive hover:bg-destructive/90"
            >
              {unenrolling ? tDetail("unenrolling") : tDetail("unenrollConfirm")}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
