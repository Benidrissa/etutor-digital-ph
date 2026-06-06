"use client";

import { CourseSourcesUsage } from "@/components/admin/course-sources-usage";

/**
 * Persistent per-course "which sources are really used" panel, reachable from the
 * course list ("Sources" action). Lets admins audit a published course's sources
 * — extracted + indexed vs silently dropped — outside the creation wizard.
 */
export function CourseSourcesClient({ courseId }: { courseId: string }) {
  return (
    <div className="max-w-3xl">
      <CourseSourcesUsage courseId={courseId} />
    </div>
  );
}
