"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Package, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { createCourseBundle } from "@/lib/api-bundles";

interface BundleTriggerProps {
  /** Pre-selected course. When set, the course picker is hidden. */
  courseId: string;
  /** Optional callback after successful trigger. */
  onSuccess?: () => void;
}

export function BundleTrigger({ courseId, onSuccess }: BundleTriggerProps) {
  const t = useTranslations("Admin.bundles.trigger");
  const tLevel = useTranslations("Admin.bundles.levelLabels");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [language, setLanguage] = useState<"fr" | "en">("fr");
  const [level, setLevel] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await createCourseBundle(courseId, { language, level, country: "SN" });
      setOpen(false);
      if (onSuccess) {
        onSuccess();
      } else {
        router.push(`/admin/bundles`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-2"
      >
        <Package className="size-4" />
        {t("title")}
      </Button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="w-full max-w-sm rounded-lg bg-background p-6 shadow-xl">
            <div className="mb-4 flex items-start justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold">{t("title")}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("description")}
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="rounded-sm text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Language */}
              <div className="space-y-2">
                <label className="text-sm font-medium">{t("language")}</label>
                <div className="flex gap-3">
                  {(["fr", "en"] as const).map((lang) => (
                    <label
                      key={lang}
                      className="flex cursor-pointer items-center gap-2"
                    >
                      <input
                        type="radio"
                        name="language"
                        value={lang}
                        checked={language === lang}
                        onChange={() => setLanguage(lang)}
                        className="accent-primary"
                      />
                      <span className="text-sm uppercase">{lang}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Level */}
              <div className="space-y-2">
                <label className="text-sm font-medium">{t("level")}</label>
                <select
                  value={level}
                  onChange={(e) => setLevel(Number(e.target.value))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {([1, 2, 3, 4] as const).map((l) => (
                    <option key={l} value={l}>
                      {l} — {tLevel(String(l) as "1" | "2" | "3" | "4")}
                    </option>
                  ))}
                </select>
              </div>

              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setOpen(false)}
                  disabled={loading}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={loading}>
                  {loading ? t("submitting") : t("submit")}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
