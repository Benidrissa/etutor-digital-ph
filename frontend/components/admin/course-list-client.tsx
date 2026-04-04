"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, MoreVertical, BookOpen, CalendarDays, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { apiFetch } from "@/lib/api";
import { CourseWizardClient } from "./course-wizard-client";

interface Course {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  module_count: number;
  status: "draft" | "published" | "archived";
  created_at: string;
  published_at: string | null;
  rag_collection_id: string | null;
}

type PendingAction =
  | { type: "publish"; course: Course }
  | { type: "archive"; course: Course }
  | { type: "delete"; course: Course };

function useAdminCourses() {
  return useQuery<Course[]>({
    queryKey: ["admin-courses"],
    queryFn: () => apiFetch<Course[]>("/api/v1/admin/courses"),
    staleTime: 30_000,
  });
}

function StatusBadge({ status }: { status: Course["status"] }) {
  const t = useTranslations("AdminCourses.status");
  const variants: Record<Course["status"], string> = {
    draft: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800",
    published:
      "bg-green-100 text-green-800 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800",
    archived:
      "bg-stone-100 text-stone-600 border-stone-200 dark:bg-stone-800 dark:text-stone-400 dark:border-stone-700",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${variants[status]}`}
    >
      {t(status)}
    </span>
  );
}

export function CourseListClient() {
  const t = useTranslations("AdminCourses");
  const queryClient = useQueryClient();
  const { data: courses, isLoading, isError } = useAdminCourses();

  const [showWizard, setShowWizard] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  const publishMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/courses/${id}/publish`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-courses"] }),
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/courses/${id}/archive`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-courses"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/courses/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-courses"] }),
  });

  const handleConfirm = () => {
    if (!pendingAction) return;
    if (pendingAction.type === "publish") publishMutation.mutate(pendingAction.course.id);
    if (pendingAction.type === "archive") archiveMutation.mutate(pendingAction.course.id);
    if (pendingAction.type === "delete") deleteMutation.mutate(pendingAction.course.id);
    setPendingAction(null);
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <AlertCircle className="h-4 w-4 shrink-0" />
        {t("errors.load")}
      </div>
    );
  }

  return (
    <>
      {showWizard && (
        <CourseWizardClient
          onClose={() => setShowWizard(false)}
          onCourseCreated={() => setShowWizard(false)}
        />
      )}

      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-muted-foreground">
          {courses?.length ?? 0} cours
        </p>
        <Button onClick={() => setShowWizard(true)} className="min-h-11">
          <Plus className="mr-2 h-4 w-4" />
          {t("newCourse")}
        </Button>
      </div>

      {!courses || courses.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
          <BookOpen className="h-8 w-8 text-muted-foreground" />
          <div>
            <p className="font-medium">{t("noCourses")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t("noCoursesDesc")}</p>
          </div>
          <Button onClick={() => setShowWizard(true)} variant="outline" className="mt-2 min-h-11">
            <Plus className="mr-2 h-4 w-4" />
            {t("newCourse")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {courses.map((course) => (
            <Card key={course.id}>
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{course.title_fr}</p>
                      <StatusBadge status={course.status} />
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">{course.title_en}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      {course.course_domain?.length > 0 && (
                        <span>{course.course_domain.map((d: string) => d.replace(/_/g, ' ')).join(', ')}</span>
                      )}
                      <span className="flex items-center gap-1">
                        <BookOpen className="h-3 w-3" />
                        {course.module_count} {t("table.modules").toLowerCase()}
                      </span>
                      <span className="flex items-center gap-1">
                        <CalendarDays className="h-3 w-3" />
                        {new Date(course.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  <DropdownMenu>
                    <DropdownMenuTrigger className="group/button inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium outline-none transition-all select-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-expanded:bg-muted aria-expanded:text-foreground">
                      <MoreVertical className="h-4 w-4" />
                      <span className="sr-only">{t("table.actions")}</span>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {course.status === "draft" && (
                        <DropdownMenuItem
                          onClick={() => setPendingAction({ type: "publish", course })}
                        >
                          {t("actions.publish")}
                        </DropdownMenuItem>
                      )}
                      {course.status === "published" && (
                        <DropdownMenuItem
                          onClick={() => setPendingAction({ type: "archive", course })}
                        >
                          {t("actions.archive")}
                        </DropdownMenuItem>
                      )}
                      {course.status !== "published" && (
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={() => setPendingAction({ type: "delete", course })}
                        >
                          {t("actions.delete")}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <AlertDialog open={!!pendingAction} onOpenChange={(o) => !o && setPendingAction(null)}>
        <AlertDialogContent>
          <AlertDialogTitle>
            {pendingAction && t(`confirm.${pendingAction.type}`)}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {pendingAction && t(`confirm.${pendingAction.type}Desc`)}
          </AlertDialogDescription>
          <div className="flex justify-end gap-2 pt-2">
            <AlertDialogCancel className="min-h-11">{t("confirm.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirm} className="min-h-11">
              {t("confirm.confirm")}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
