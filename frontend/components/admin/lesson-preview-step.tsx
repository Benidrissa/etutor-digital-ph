"use client";

import { useState, useCallback, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Pencil,
  Lock,
  Loader2,
  CheckCircle2,
  AlertCircle,
  BookOpen,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  type SyllabusModule,
  type LessonPreviewResponse,
  type LessonContent,
  getCourseSyllabus,
  previewLesson,
  editContent,
} from "@/lib/api-course-admin";

interface LessonPreviewStepProps {
  courseId: string;
}

interface PreviewState {
  loading: boolean;
  data: LessonPreviewResponse | null;
  error: string | null;
  editing: boolean;
  editedContent: LessonContent | null;
  saving: boolean;
  locked: boolean;
}

export function LessonPreviewStep({ courseId }: LessonPreviewStepProps) {
  const t = useTranslations("AdminCourses.lessonPreview");
  const locale = useLocale();

  const [modules, setModules] = useState<SyllabusModule[]>([]);
  const [isLoadingModules, setIsLoadingModules] = useState(true);
  const [expandedModule, setExpandedModule] = useState<number | null>(null);
  // Preview controls
  const [language, setLanguage] = useState("fr");
  const [country, setCountry] = useState("SN");

  // Preview state per unit key
  const [previews, setPreviews] = useState<Record<string, PreviewState>>({});

  // Fetch modules on mount
  useEffect(() => {
    let cancelled = false;
    getCourseSyllabus(courseId)
      .then((data) => {
        if (!cancelled) setModules(data.modules);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setIsLoadingModules(false);
      });
    return () => { cancelled = true; };
  }, [courseId]);

  const getPreviewKey = useCallback(
    (moduleNumber: number, unitIdx: number) =>
      `${moduleNumber}-${unitIdx}-${language}-${country}`,
    [language, country]
  );

  const generatePreview = useCallback(
    async (moduleId: string, moduleNumber: number, unitIdx: number) => {
      const unitId = `${moduleNumber}.${unitIdx + 1}`;
      const key = getPreviewKey(moduleNumber, unitIdx);

      setPreviews((prev) => ({
        ...prev,
        [key]: { loading: true, data: null, error: null, editing: false, editedContent: null, saving: false, locked: false },
      }));

      try {
        const result = await previewLesson(courseId, moduleId, unitId, language, country);
        setPreviews((prev) => ({
          ...prev,
          [key]: { ...prev[key], loading: false, data: result, locked: false },
        }));
      } catch {
        setPreviews((prev) => ({
          ...prev,
          [key]: { ...prev[key], loading: false, error: t("generateError") },
        }));
      }
    },
    [courseId, language, country, t, getPreviewKey]
  );

  const toggleEdit = useCallback((key: string) => {
    setPreviews((prev) => {
      const p = prev[key];
      if (!p?.data) return prev;
      return {
        ...prev,
        [key]: {
          ...p,
          editing: !p.editing,
          editedContent: p.editing ? null : { ...p.data.content },
        },
      };
    });
  }, []);

  const updateEditField = useCallback(
    (key: string, field: keyof LessonContent, value: string | string[]) => {
      setPreviews((prev) => {
        const p = prev[key];
        if (!p?.editedContent) return prev;
        return {
          ...prev,
          [key]: {
            ...p,
            editedContent: { ...p.editedContent, [field]: value },
          },
        };
      });
    },
    []
  );

  const saveEdit = useCallback(
    async (key: string) => {
      const p = previews[key];
      if (!p?.data || !p.editedContent) return;

      setPreviews((prev) => ({
        ...prev,
        [key]: { ...prev[key], saving: true },
      }));

      try {
        await editContent(courseId, p.data.id, p.editedContent);
        setPreviews((prev) => ({
          ...prev,
          [key]: {
            ...prev[key],
            saving: false,
            editing: false,
            locked: true,
            data: { ...prev[key].data!, content: prev[key].editedContent! },
            editedContent: null,
          },
        }));
      } catch {
        setPreviews((prev) => ({
          ...prev,
          [key]: { ...prev[key], saving: false },
        }));
      }
    },
    [courseId, previews]
  );

  if (isLoadingModules) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Language / Country selectors */}
      <div className="flex gap-3 flex-wrap">
        <div className="space-y-1">
          <Label className="text-xs">{t("language")}</Label>
          <Select value={language} onValueChange={(v) => v && setLanguage(v)}>
            <SelectTrigger className="w-[120px] h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fr">Fran\u00e7ais</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{t("country")}</Label>
          <Select value={country} onValueChange={(v) => v && setCountry(v)}>
            <SelectTrigger className="w-[120px] h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SN">S\u00e9n\u00e9gal</SelectItem>
              <SelectItem value="ML">Mali</SelectItem>
              <SelectItem value="BF">Burkina Faso</SelectItem>
              <SelectItem value="CI">C\u00f4te d&apos;Ivoire</SelectItem>
              <SelectItem value="GH">Ghana</SelectItem>
              <SelectItem value="NG">Nigeria</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Module / Unit tree */}
      {modules.map((mod, mIdx) => (
        <div key={mIdx} className="rounded-lg border bg-card overflow-hidden">
          <button
            type="button"
            className="flex w-full items-center gap-2 p-3 text-left min-h-[44px] hover:bg-muted/50"
            onClick={() => setExpandedModule(expandedModule === mIdx ? null : mIdx)}
          >
            {expandedModule === mIdx ? (
              <ChevronDown className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0" />
            )}
            <Badge variant="outline" className="shrink-0 text-xs">
              M{mod.module_number}
            </Badge>
            <span className="text-sm font-medium truncate">
              {locale === "fr" ? mod.title_fr : mod.title_en}
            </span>
            <span className="text-xs text-muted-foreground ml-auto shrink-0">
              {mod.units.length} {t("units")}
            </span>
          </button>

          {expandedModule === mIdx && (
            <div className="border-t px-3 pb-3 pt-2 space-y-2">
              {mod.units
                .filter((u) => u.unit_type === "lesson")
                .map((unit, uIdx) => {
                  const key = getPreviewKey(mod.module_number, uIdx);
                  const preview = previews[key];
                  const unitTitle = locale === "fr" ? unit.title_fr : unit.title_en;

                  return (
                    <div key={uIdx} className="space-y-2">
                      <div className="flex items-center gap-2 rounded border bg-background p-2">
                        <BookOpen className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="text-sm truncate flex-1">{unitTitle || `Unit ${mod.module_number}.${uIdx + 1}`}</span>

                        {preview?.locked && (
                          <Badge className="gap-1 bg-amber-100 text-amber-800 border-amber-300 text-[10px] shrink-0">
                            <Lock className="h-2.5 w-2.5" />
                            {t("locked")}
                          </Badge>
                        )}

                        {preview?.data && !preview.loading && (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 gap-1 text-xs shrink-0"
                              onClick={() => toggleEdit(key)}
                            >
                              {preview.editing ? <Eye className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
                              {preview.editing ? t("view") : t("edit")}
                            </Button>
                          </>
                        )}

                        {!preview?.data && !preview?.loading && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 gap-1 text-xs shrink-0"
                            onClick={() => generatePreview(mod.id || "", mod.module_number, uIdx)}
                            disabled={!mod.id}
                          >
                            <Eye className="h-3 w-3" />
                            {t("generate")}
                          </Button>
                        )}

                        {preview?.loading && (
                          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
                        )}
                      </div>

                      {preview?.error && (
                        <div className="flex items-center gap-2 rounded border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" />
                          {preview.error}
                        </div>
                      )}

                      {/* Preview content */}
                      {preview?.data && !preview.editing && (
                        <div className="rounded border bg-muted/20 p-3 max-h-96 overflow-y-auto">
                          <div className="prose prose-sm dark:prose-invert max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {preview.data.content.introduction}
                            </ReactMarkdown>
                            {preview.data.content.concepts.map((c, i) => (
                              <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>
                                {c}
                              </ReactMarkdown>
                            ))}
                            {preview.data.content.key_points.length > 0 && (
                              <>
                                <h4>{t("keyPoints")}</h4>
                                <ul>
                                  {preview.data.content.key_points.map((kp, i) => (
                                    <li key={i}>
                                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{kp}</ReactMarkdown>
                                    </li>
                                  ))}
                                </ul>
                              </>
                            )}
                          </div>
                          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                            {preview.data.cached && (
                              <Badge variant="secondary" className="text-[10px]">
                                <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" />
                                {t("cached")}
                              </Badge>
                            )}
                            <span>{preview.data.language.toUpperCase()}</span>
                            <span>{preview.data.country_context}</span>
                          </div>
                        </div>
                      )}

                      {/* Edit mode */}
                      {preview?.editing && preview.editedContent && (
                        <div className="rounded border bg-muted/20 p-3 space-y-3">
                          <div className="space-y-1.5">
                            <Label className="text-xs font-medium">{t("editIntroduction")}</Label>
                            <Textarea
                              value={preview.editedContent.introduction}
                              onChange={(e) => updateEditField(key, "introduction", e.target.value)}
                              className="min-h-[100px] text-sm"
                            />
                          </div>

                          {preview.editedContent.concepts.map((concept, i) => (
                            <div key={i} className="space-y-1.5">
                              <Label className="text-xs font-medium">{t("editConcept", { n: i + 1 })}</Label>
                              <Textarea
                                value={concept}
                                onChange={(e) => {
                                  const updated = [...preview.editedContent!.concepts];
                                  updated[i] = e.target.value;
                                  updateEditField(key, "concepts", updated);
                                }}
                                className="min-h-[80px] text-sm"
                              />
                            </div>
                          ))}

                          <div className="space-y-1.5">
                            <Label className="text-xs font-medium">{t("editSynthesis")}</Label>
                            <Textarea
                              value={preview.editedContent.synthesis}
                              onChange={(e) => updateEditField(key, "synthesis", e.target.value)}
                              className="min-h-[80px] text-sm"
                            />
                          </div>

                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={() => saveEdit(key)}
                              disabled={preview.saving}
                              className="gap-1 min-h-[36px]"
                            >
                              {preview.saving ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Save className="h-3 w-3" />
                              )}
                              {t("saveAndLock")}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => toggleEdit(key)}
                              className="min-h-[36px]"
                            >
                              {t("cancel")}
                            </Button>
                          </div>

                          <p className="text-xs text-muted-foreground flex items-center gap-1">
                            <Lock className="h-3 w-3" />
                            {t("lockHint")}
                          </p>
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      ))}

      {modules.length === 0 && (
        <div className="text-center py-8 text-sm text-muted-foreground">
          {t("noModules")}
        </div>
      )}
    </div>
  );
}
