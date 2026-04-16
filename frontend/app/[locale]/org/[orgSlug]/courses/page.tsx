"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import { AICourseWizard } from "@/components/admin/ai-course-wizard";
import { fetchOrgCourses } from "@/lib/api";
import { Plus, GraduationCap, Loader2, Play } from "lucide-react";

interface OrgCourse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  status: string;
  creation_mode: string;
  creation_step: string;
  created_at: string;
  cover_image_url?: string;
}

export default function OrgCoursesPage() {
  const t = useTranslations("Organization");
  const locale = useLocale();
  const { orgId } = useOrg();
  const [courses, setCourses] = useState<OrgCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [resumeCourse, setResumeCourse] = useState<OrgCourse | null>(null);

  const loadCourses = () => {
    if (!orgId) return;
    fetchOrgCourses(orgId)
      .then(setCourses)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadCourses();
  }, [orgId]);

  const handleCourseCreated = () => {
    setWizardOpen(false);
    setResumeCourse(null);
    loadCourses();
  };

  const handleResume = (course: OrgCourse) => {
    setResumeCourse(course);
    setWizardOpen(true);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-green-600" />
      </div>
    );
  }

  if (wizardOpen) {
    return (
      <AICourseWizard
        onClose={() => {
          setWizardOpen(false);
          setResumeCourse(null);
        }}
        onCourseCreated={handleCourseCreated}
        resumeCourseId={resumeCourse?.id}
        resumeCreationStep={resumeCourse?.creation_step}
        organizationId={orgId ?? undefined}
      />
    );
  }

  const statusColors: Record<string, string> = {
    draft: "bg-gray-100 text-gray-600",
    published: "bg-green-100 text-green-700",
    archived: "bg-amber-100 text-amber-700",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Courses</h1>
        <button
          onClick={() => setWizardOpen(true)}
          className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
        >
          <Plus className="h-4 w-4" />
          Create Course (AI)
        </button>
      </div>

      {courses.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center">
          <GraduationCap className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-600 font-medium">No courses yet</p>
          <p className="text-sm text-gray-500 mt-1">
            Create your first AI-assisted course for this organization.
          </p>
          <button
            onClick={() => setWizardOpen(true)}
            className="inline-flex items-center gap-2 mt-4 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
          >
            <Plus className="h-4 w-4" />
            Create Course (AI)
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {courses.map((c) => {
            const title = locale === "fr" ? c.title_fr : c.title_en;
            const isInProgress =
              c.status === "draft" && c.creation_step !== "published";
            return (
              <div
                key={c.id}
                className="flex items-center justify-between rounded-lg border bg-white p-4"
              >
                <div className="flex items-center gap-3">
                  {c.cover_image_url ? (
                    <img
                      src={c.cover_image_url}
                      alt={title}
                      className="h-12 w-12 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="h-12 w-12 rounded-lg bg-green-100 flex items-center justify-center">
                      <GraduationCap className="h-6 w-6 text-green-600" />
                    </div>
                  )}
                  <div>
                    <p className="font-medium">{title}</p>
                    <p className="text-xs text-gray-500">
                      {c.creation_mode === "ai_assisted"
                        ? "AI Assisted"
                        : "Legacy"}{" "}
                      · {c.creation_step}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      statusColors[c.status] || "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {c.status}
                  </span>
                  {isInProgress && (
                    <button
                      onClick={() => handleResume(c)}
                      className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-gray-50"
                    >
                      <Play className="h-3.5 w-3.5" />
                      Resume
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
