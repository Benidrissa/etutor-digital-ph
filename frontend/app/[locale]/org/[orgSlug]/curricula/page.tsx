"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import {
  fetchOrgCurricula,
  createOrgCurriculum,
} from "@/lib/api";
import type { OrgCurriculumResponse } from "@/lib/api";
import { Library, Plus, BookOpen } from "lucide-react";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export default function OrgCurriculaPage() {
  const t = useTranslations("Organization");
  const { orgId } = useOrg();
  const [curricula, setCurricula] = useState<OrgCurriculumResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [titleFr, setTitleFr] = useState("");
  const [titleEn, setTitleEn] = useState("");
  const [descFr, setDescFr] = useState("");
  const [descEn, setDescEn] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!orgId) return;
    fetchOrgCurricula(orgId)
      .then(setCurricula)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [orgId]);

  const handleCreate = async () => {
    if (!orgId || !titleFr.trim() || !titleEn.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const c = await createOrgCurriculum(orgId, {
        title_fr: titleFr.trim(),
        title_en: titleEn.trim(),
        slug: slugify(titleEn.trim()),
        description_fr: descFr || undefined,
        description_en: descEn || undefined,
      });
      setCurricula((prev) => [c, ...prev]);
      setShowForm(false);
      setTitleFr("");
      setTitleEn("");
      setDescFr("");
      setDescEn("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create curriculum");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("curricula")}</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
        >
          <Plus className="h-4 w-4" />
          {t("curricula")}
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border bg-white p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Titre (FR) *
              </label>
              <input
                type="text"
                value={titleFr}
                onChange={(e) => setTitleFr(e.target.value)}
                className="w-full rounded-md border px-3 py-2 text-sm"
                placeholder="Mon curriculum"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Title (EN) *
              </label>
              <input
                type="text"
                value={titleEn}
                onChange={(e) => setTitleEn(e.target.value)}
                className="w-full rounded-md border px-3 py-2 text-sm"
                placeholder="My curriculum"
              />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description (FR)
              </label>
              <textarea
                value={descFr}
                onChange={(e) => setDescFr(e.target.value)}
                rows={2}
                className="w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description (EN)
              </label>
              <textarea
                value={descEn}
                onChange={(e) => setDescEn(e.target.value)}
                rows={2}
                className="w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
          </div>
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
          <button
            onClick={handleCreate}
            disabled={submitting || !titleFr.trim() || !titleEn.trim()}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? "..." : t("curricula")}
          </button>
        </div>
      )}

      {curricula.length === 0 ? (
        <div className="rounded-lg border bg-white p-12 text-center">
          <Library className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-600">No curricula yet. Create one to start distributing courses.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {curricula.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-lg border bg-white p-4"
            >
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-green-100 flex items-center justify-center">
                  <BookOpen className="h-5 w-5 text-green-600" />
                </div>
                <div>
                  <p className="font-medium">{c.title_en}</p>
                  <p className="text-sm text-gray-500">{c.title_fr}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-500">
                  {c.course_count} courses
                </span>
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    c.status === "published"
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {c.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
