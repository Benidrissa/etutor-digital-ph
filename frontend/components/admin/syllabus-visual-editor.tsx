"use client";

import { useState, useCallback, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  ChevronDown,
  ChevronUp,
  Plus,
  Trash2,
  GripVertical,
  BookOpen,
  HelpCircle,
  FileText,
  Save,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import {
  type SyllabusModule,
  getCourseSyllabus,
} from "@/lib/api-course-admin";

interface SyllabusVisualEditorProps {
  courseId: string;
  fetchOnMount?: boolean;
  initialModules?: SyllabusModule[];
  onSaved?: () => void;
}

const UNIT_TYPE_ICONS: Record<string, React.ReactNode> = {
  lesson: <BookOpen className="h-3.5 w-3.5" />,
  quiz: <HelpCircle className="h-3.5 w-3.5" />,
  "case-study": <FileText className="h-3.5 w-3.5" />,
};

export function SyllabusVisualEditor({
  courseId,
  initialModules = [],
  fetchOnMount = false,
  onSaved,
}: SyllabusVisualEditorProps) {
  const t = useTranslations("AdminCourses.syllabusEditor");
  const locale = useLocale();
  const [modules, setModules] = useState<SyllabusModule[]>(initialModules);
  const [expandedModule, setExpandedModule] = useState<number | null>(
    initialModules.length > 0 ? 0 : null
  );
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch full syllabus from backend when initialModules is empty
  useEffect(() => {
    if (!fetchOnMount || initialModules.length > 0) return;
    setIsLoading(true);
    getCourseSyllabus(courseId)
      .then((data) => {
        if (data.modules.length > 0) {
          setModules(data.modules);
          setExpandedModule(0);
        }
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, [courseId, fetchOnMount]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Module operations ─────────────────────────────────────────────

  const addModule = useCallback(() => {
    const newNum = modules.length + 1;
    setModules((prev) => [
      ...prev,
      {
        module_number: newNum,
        title_fr: "",
        title_en: "",
        description_fr: "",
        description_en: "",
        estimated_hours: 20,
        bloom_level: "understand",
        units: [
          {
            title_fr: "",
            title_en: "",
            unit_type: "lesson",
            description_fr: "",
            description_en: "",
          },
        ],
      },
    ]);
    setExpandedModule(modules.length);
  }, [modules.length]);

  const removeModule = useCallback(
    (idx: number) => {
      setModules((prev) => {
        const next = prev.filter((_, i) => i !== idx);
        return next.map((m, i) => ({ ...m, module_number: i + 1 }));
      });
      if (expandedModule === idx) setExpandedModule(null);
    },
    [expandedModule]
  );

  const moveModule = useCallback((idx: number, direction: "up" | "down") => {
    setModules((prev) => {
      const next = [...prev];
      const targetIdx = direction === "up" ? idx - 1 : idx + 1;
      if (targetIdx < 0 || targetIdx >= next.length) return prev;
      [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
      return next.map((m, i) => ({ ...m, module_number: i + 1 }));
    });
  }, []);

  const updateModuleTitle = useCallback(
    (idx: number, lang: "fr" | "en", value: string) => {
      setModules((prev) =>
        prev.map((m, i) =>
          i === idx
            ? { ...m, [lang === "fr" ? "title_fr" : "title_en"]: value }
            : m
        )
      );
    },
    []
  );

  // ── Unit operations ───────────────────────────────────────────────

  const addUnit = useCallback((moduleIdx: number) => {
    setModules((prev) =>
      prev.map((m, i) =>
        i === moduleIdx
          ? {
              ...m,
              units: [
                ...m.units,
                {
                  title_fr: "",
                  title_en: "",
                  unit_type: "lesson",
                  description_fr: "",
                  description_en: "",
                },
              ],
            }
          : m
      )
    );
  }, []);

  const removeUnit = useCallback((moduleIdx: number, unitIdx: number) => {
    setModules((prev) =>
      prev.map((m, i) =>
        i === moduleIdx
          ? { ...m, units: m.units.filter((_, j) => j !== unitIdx) }
          : m
      )
    );
  }, []);

  const moveUnit = useCallback(
    (moduleIdx: number, unitIdx: number, direction: "up" | "down") => {
      setModules((prev) =>
        prev.map((m, i) => {
          if (i !== moduleIdx) return m;
          const units = [...m.units];
          const targetIdx = direction === "up" ? unitIdx - 1 : unitIdx + 1;
          if (targetIdx < 0 || targetIdx >= units.length) return m;
          [units[unitIdx], units[targetIdx]] = [
            units[targetIdx],
            units[unitIdx],
          ];
          return { ...m, units };
        })
      );
    },
    []
  );

  const updateUnitTitle = useCallback(
    (moduleIdx: number, unitIdx: number, lang: "fr" | "en", value: string) => {
      setModules((prev) =>
        prev.map((m, i) =>
          i === moduleIdx
            ? {
                ...m,
                units: m.units.map((u, j) =>
                  j === unitIdx
                    ? {
                        ...u,
                        [lang === "fr" ? "title_fr" : "title_en"]: value,
                      }
                    : u
                ),
              }
            : m
        )
      );
    },
    []
  );

  // ── Save ──────────────────────────────────────────────────────────

  const saveSyllabus = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await apiFetch(`/api/v1/admin/courses/${courseId}/syllabus`, {
        method: "PATCH",
        body: JSON.stringify({ modules }),
      });
      setSaveSuccess(true);
      onSaved?.();
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      setSaveError(t("saveError"));
    } finally {
      setIsSaving(false);
    }
  }, [courseId, modules, onSaved, t]);

  // ── Render ────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {modules.map((mod, mIdx) => (
        <div
          key={mIdx}
          className="rounded-lg border bg-card overflow-hidden"
        >
          {/* Module header */}
          <div className="flex items-center gap-2 p-3 border-b bg-muted/30">
            <div className="flex flex-col gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                disabled={mIdx === 0}
                onClick={() => moveModule(mIdx, "up")}
              >
                <ChevronUp className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                disabled={mIdx === modules.length - 1}
                onClick={() => moveModule(mIdx, "down")}
              >
                <ChevronDown className="h-3 w-3" />
              </Button>
            </div>

            <Badge variant="outline" className="shrink-0 text-xs">
              M{mod.module_number}
            </Badge>

            <button
              type="button"
              className="flex-1 text-left min-w-0"
              onClick={() =>
                setExpandedModule(expandedModule === mIdx ? null : mIdx)
              }
            >
              <p className="text-sm font-medium truncate">
                {(locale === "fr" ? mod.title_fr : mod.title_en) ||
                  t("untitledModule")}
              </p>
              <p className="text-xs text-muted-foreground">
                {mod.units.length} {t("units")}
              </p>
            </button>

            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 text-destructive hover:text-destructive"
              onClick={() => removeModule(mIdx)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>

          {/* Module expanded content */}
          {expandedModule === mIdx && (
            <div className="p-3 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Input
                  value={mod.title_fr}
                  onChange={(e) =>
                    updateModuleTitle(mIdx, "fr", e.target.value)
                  }
                  placeholder={t("titleFrPlaceholder")}
                  className="text-sm"
                />
                <Input
                  value={mod.title_en}
                  onChange={(e) =>
                    updateModuleTitle(mIdx, "en", e.target.value)
                  }
                  placeholder={t("titleEnPlaceholder")}
                  className="text-sm"
                />
              </div>

              {/* Units */}
              <div className="space-y-2 pl-4 border-l-2 border-primary/20">
                {mod.units.map((unit, uIdx) => (
                  <div
                    key={uIdx}
                    className="flex items-center gap-2 rounded border bg-background p-2"
                  >
                    <div className="flex flex-col gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-4 w-4"
                        disabled={uIdx === 0}
                        onClick={() => moveUnit(mIdx, uIdx, "up")}
                      >
                        <ChevronUp className="h-2.5 w-2.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-4 w-4"
                        disabled={uIdx === mod.units.length - 1}
                        onClick={() => moveUnit(mIdx, uIdx, "down")}
                      >
                        <ChevronDown className="h-2.5 w-2.5" />
                      </Button>
                    </div>

                    <div className="text-muted-foreground shrink-0">
                      {UNIT_TYPE_ICONS[unit.unit_type] || (
                        <GripVertical className="h-3.5 w-3.5" />
                      )}
                    </div>

                    <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-1 min-w-0">
                      <Input
                        value={unit.title_fr}
                        onChange={(e) =>
                          updateUnitTitle(mIdx, uIdx, "fr", e.target.value)
                        }
                        placeholder={t("unitTitleFrPlaceholder")}
                        className="text-xs h-8"
                      />
                      <Input
                        value={unit.title_en}
                        onChange={(e) =>
                          updateUnitTitle(mIdx, uIdx, "en", e.target.value)
                        }
                        placeholder={t("unitTitleEnPlaceholder")}
                        className="text-xs h-8"
                      />
                    </div>

                    <Badge variant="secondary" className="text-[10px] shrink-0">
                      {unit.unit_type}
                    </Badge>

                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0 text-destructive hover:text-destructive"
                      onClick={() => removeUnit(mIdx, uIdx)}
                      disabled={mod.units.length <= 1}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}

                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full min-h-[36px] border border-dashed"
                  onClick={() => addUnit(mIdx)}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  {t("addUnit")}
                </Button>
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Add module button */}
      <Button
        variant="outline"
        className="w-full min-h-[44px] border-dashed"
        onClick={addModule}
      >
        <Plus className="mr-2 h-4 w-4" />
        {t("addModule")}
      </Button>

      {/* Save button */}
      {modules.length > 0 && (
        <div className="space-y-2 pt-2">
          {saveError && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {saveError}
            </div>
          )}
          {saveSuccess && (
            <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700 dark:border-green-900 dark:bg-green-950 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              {t("saveSuccess")}
            </div>
          )}
          <Button
            onClick={saveSyllabus}
            disabled={isSaving}
            className="w-full min-h-[44px]"
          >
            {isSaving ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            {t("save")}
          </Button>
        </div>
      )}
    </div>
  );
}
