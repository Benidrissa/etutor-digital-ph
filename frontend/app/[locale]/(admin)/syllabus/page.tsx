"use client";

import { useState, useCallback } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  Shield,
  ChevronDown,
  ChevronRight,
  Plus,
  Pencil,
  Trash2,
  RotateCcw,
  BookOpen,
  MessageSquare,
  FileText,
  Loader2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CURRICULUM_MODULES } from "@/lib/modules";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiUnit {
  id: string;
  module_id: string;
  unit_number: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  estimated_minutes: number;
  order_index: number;
  unit_type: "lesson" | "quiz" | "case-study";
  books_sources: Record<string, string[]> | null;
}

interface UnitFormData {
  unit_number: string;
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
  estimated_minutes: number;
  order_index: number;
  unit_type: "lesson" | "quiz" | "case-study";
}

const EMPTY_FORM: UnitFormData = {
  unit_number: "",
  title_fr: "",
  title_en: "",
  description_fr: "",
  description_en: "",
  estimated_minutes: 30,
  order_index: 1,
  unit_type: "lesson",
};

function unitTypeIcon(type: string) {
  if (type === "quiz") return <MessageSquare className="w-3.5 h-3.5" />;
  if (type === "case-study") return <FileText className="w-3.5 h-3.5" />;
  return <BookOpen className="w-3.5 h-3.5" />;
}

function unitTypeBadgeVariant(
  type: string
): "default" | "secondary" | "outline" {
  if (type === "quiz") return "secondary";
  if (type === "case-study") return "outline";
  return "default";
}

function UnitForm({
  form,
  setForm,
  onSubmit,
  onCancel,
  isPending,
  isEdit,
  error,
  t,
}: {
  form: UnitFormData;
  setForm: React.Dispatch<React.SetStateAction<UnitFormData>>;
  onSubmit: () => void;
  onCancel: () => void;
  isPending: boolean;
  isEdit: boolean;
  error: string | null;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className="rounded-md border border-teal-200 bg-teal-50 p-4 space-y-3">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-teal-900">
          {isEdit ? t("editUnit") : t("addUnit")}
        </p>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onCancel}>
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="f_unit_number">
            {t("unitNumber")}
          </Label>
          <Input
            id="f_unit_number"
            className="h-8 text-sm"
            placeholder="U01.1"
            value={form.unit_number}
            onChange={(e) =>
              setForm((f) => ({ ...f, unit_number: e.target.value }))
            }
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="f_unit_type">
            {t("unitType")}
          </Label>
          <Select
            value={form.unit_type}
            onValueChange={(v) =>
              setForm((f) => ({
                ...f,
                unit_type: v as UnitFormData["unit_type"],
              }))
            }
          >
            <SelectTrigger id="f_unit_type" className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="lesson">{t("typeLesson")}</SelectItem>
              <SelectItem value="quiz">{t("typeQuiz")}</SelectItem>
              <SelectItem value="case-study">{t("typeCaseStudy")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-1">
        <Label className="text-xs" htmlFor="f_title_fr">
          {t("titleFr")}
        </Label>
        <Input
          id="f_title_fr"
          className="h-8 text-sm"
          value={form.title_fr}
          onChange={(e) => setForm((f) => ({ ...f, title_fr: e.target.value }))}
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs" htmlFor="f_title_en">
          {t("titleEn")}
        </Label>
        <Input
          id="f_title_en"
          className="h-8 text-sm"
          value={form.title_en}
          onChange={(e) => setForm((f) => ({ ...f, title_en: e.target.value }))}
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs" htmlFor="f_desc_fr">
          {t("descFr")}
        </Label>
        <Input
          id="f_desc_fr"
          className="h-8 text-sm"
          value={form.description_fr}
          onChange={(e) =>
            setForm((f) => ({ ...f, description_fr: e.target.value }))
          }
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs" htmlFor="f_desc_en">
          {t("descEn")}
        </Label>
        <Input
          id="f_desc_en"
          className="h-8 text-sm"
          value={form.description_en}
          onChange={(e) =>
            setForm((f) => ({ ...f, description_en: e.target.value }))
          }
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="f_minutes">
            {t("estimatedMinutes")}
          </Label>
          <Input
            id="f_minutes"
            type="number"
            min={1}
            className="h-8 text-sm"
            value={form.estimated_minutes}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                estimated_minutes: Number(e.target.value),
              }))
            }
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs" htmlFor="f_order">
            {t("orderIndex")}
          </Label>
          <Input
            id="f_order"
            type="number"
            min={1}
            className="h-8 text-sm"
            value={form.order_index}
            onChange={(e) =>
              setForm((f) => ({ ...f, order_index: Number(e.target.value) }))
            }
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={isPending}>
          {t("cancel")}
        </Button>
        <Button size="sm" onClick={onSubmit} disabled={isPending}>
          {isPending && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
          {isEdit ? t("save") : t("create")}
        </Button>
      </div>
    </div>
  );
}

function ModuleSection({ moduleCode }: { moduleCode: string }) {
  const t = useTranslations("Admin");
  const locale = useLocale() as "en" | "fr";
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editUnit, setEditUnit] = useState<ApiUnit | null>(null);
  const [form, setForm] = useState<UnitFormData>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  const moduleData = CURRICULUM_MODULES.find((m) => m.id === moduleCode);

  const { data: unitsData, isLoading } = useQuery({
    queryKey: ["admin-units", moduleCode],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/v1/modules/${moduleCode}/units`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
      if (!res.ok) throw new Error("Failed to fetch units");
      return res.json() as Promise<{ units: ApiUnit[]; total: number }>;
    },
    enabled: expanded,
  });

  const createMutation = useMutation({
    mutationFn: async (data: UnitFormData) => {
      const res = await fetch(`${API_BASE}/api/v1/modules/${moduleCode}/units`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
        body: JSON.stringify({
          ...data,
          estimated_minutes: Number(data.estimated_minutes),
          order_index: Number(data.order_index),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as {
          detail?: { message?: string };
        };
        throw new Error(err?.detail?.message ?? "Failed to create unit");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-units", moduleCode] });
      setFormOpen(false);
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: string;
      data: Partial<UnitFormData>;
    }) => {
      const res = await fetch(
        `${API_BASE}/api/v1/modules/${moduleCode}/units/${id}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("access_token")}`,
          },
          body: JSON.stringify({
            ...data,
            estimated_minutes: Number(data.estimated_minutes),
            order_index: Number(data.order_index),
          }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as {
          detail?: { message?: string };
        };
        throw new Error(err?.detail?.message ?? "Failed to update unit");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-units", moduleCode] });
      setFormOpen(false);
      setEditUnit(null);
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: async (unitId: string) => {
      const res = await fetch(
        `${API_BASE}/api/v1/modules/${moduleCode}/units/${unitId}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token")}`,
          },
        }
      );
      if (!res.ok) throw new Error("Failed to delete unit");
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-units", moduleCode] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const openCreate = useCallback(() => {
    setEditUnit(null);
    setForm(EMPTY_FORM);
    setError(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((unit: ApiUnit) => {
    setEditUnit(unit);
    setForm({
      unit_number: unit.unit_number,
      title_fr: unit.title_fr,
      title_en: unit.title_en,
      description_fr: unit.description_fr ?? "",
      description_en: unit.description_en ?? "",
      estimated_minutes: unit.estimated_minutes,
      order_index: unit.order_index,
      unit_type: unit.unit_type,
    });
    setError(null);
    setFormOpen(true);
  }, []);

  const handleSubmit = () => {
    if (editUnit) {
      updateMutation.mutate({ id: editUnit.id, data: form });
    } else {
      createMutation.mutate(form);
    }
  };

  const handleCancel = () => {
    setFormOpen(false);
    setEditUnit(null);
    setError(null);
  };

  if (!moduleData) return null;

  const units = unitsData?.units ?? [];
  const title =
    locale === "fr" ? moduleData.title.fr : moduleData.title.en;
  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Card className="overflow-hidden">
      <CardHeader
        className="cursor-pointer select-none py-3 px-4 hover:bg-stone-50 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            {expanded ? (
              <ChevronDown className="w-4 h-4 shrink-0 text-stone-500" />
            ) : (
              <ChevronRight className="w-4 h-4 shrink-0 text-stone-500" />
            )}
            <Badge variant="outline" className="shrink-0 font-mono text-xs">
              {moduleCode}
            </Badge>
            <CardTitle className="text-sm font-medium truncate">
              {title}
            </CardTitle>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {unitsData && (
              <span className="text-xs text-stone-500">
                {unitsData.total} {t("units")}
              </span>
            )}
            {isLoading && expanded && (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-stone-400" />
            )}
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="pt-0 pb-3 px-4 space-y-2">
          {error && !formOpen && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {units.map((unit) => (
            <div
              key={unit.id}
              className="flex items-start justify-between gap-2 rounded-md border border-stone-100 bg-stone-50 px-3 py-2"
            >
              <div className="flex items-start gap-2 min-w-0">
                <Badge
                  variant={unitTypeBadgeVariant(unit.unit_type)}
                  className="mt-0.5 shrink-0 gap-1 text-xs"
                >
                  {unitTypeIcon(unit.unit_type)}
                  {unit.unit_type}
                </Badge>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-stone-900 truncate">
                    {locale === "fr" ? unit.title_fr : unit.title_en}
                  </p>
                  <p className="text-xs text-stone-500">
                    {unit.unit_number} · {unit.estimated_minutes} min
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => openEdit(unit)}
                >
                  <Pencil className="w-3.5 h-3.5" />
                  <span className="sr-only">{t("edit")}</span>
                </Button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-red-500 hover:text-red-700 hover:bg-red-50"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span className="sr-only">{t("delete")}</span>
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t("confirmDelete")}</AlertDialogTitle>
                      <AlertDialogDescription>
                        {t("confirmDeleteDesc")}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => deleteMutation.mutate(unit.id)}
                        className="bg-red-600 hover:bg-red-700"
                      >
                        {deleteMutation.isPending ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          t("delete")
                        )}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
          ))}

          {units.length === 0 && !isLoading && !formOpen && (
            <p className="text-xs text-stone-400 text-center py-4">
              {t("noUnits")}
            </p>
          )}

          {formOpen ? (
            <UnitForm
              form={form}
              setForm={setForm}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              isPending={isPending}
              isEdit={!!editUnit}
              error={error}
              t={t}
            />
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-2"
              onClick={openCreate}
            >
              <Plus className="w-3.5 h-3.5" />
              {t("addUnit")}
            </Button>
          )}
        </CardContent>
      )}
    </Card>
  );
}

const LEVELS = [1, 2, 3, 4] as const;
const LEVEL_MODULES: Record<number, string[]> = {
  1: ["M01", "M02", "M03"],
  2: ["M04", "M05", "M06", "M07"],
  3: ["M08", "M09", "M10", "M11", "M12"],
  4: ["M13", "M14", "M15"],
};

export default function AdminSyllabusPage() {
  const t = useTranslations("Admin");
  const queryClient = useQueryClient();
  const [reseeding, setReseeding] = useState(false);
  const [reseedError, setReseedError] = useState<string | null>(null);
  const [reseedSuccess, setReseedSuccess] = useState(false);

  const handleReseed = async () => {
    setReseeding(true);
    setReseedError(null);
    setReseedSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/v1/modules/reseed`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
      if (!res.ok) throw new Error("Reseed failed");
      queryClient.invalidateQueries({ queryKey: ["admin-units"] });
      setReseedSuccess(true);
    } catch (e) {
      setReseedError(e instanceof Error ? e.message : "Failed");
    } finally {
      setReseeding(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-stone-900 flex items-center gap-2">
            <Shield className="w-5 h-5 text-amber-600" />
            {t("syllabusTitle")}
          </h1>
          <p className="mt-1 text-sm text-stone-600">{t("syllabusDesc")}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0 gap-2"
          onClick={handleReseed}
          disabled={reseeding}
        >
          {reseeding ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RotateCcw className="w-3.5 h-3.5" />
          )}
          {t("reseed")}
        </Button>
      </div>

      {reseedError && (
        <Alert variant="destructive">
          <AlertDescription>{reseedError}</AlertDescription>
        </Alert>
      )}
      {reseedSuccess && (
        <Alert>
          <AlertDescription>{t("reseedSuccess")}</AlertDescription>
        </Alert>
      )}

      {LEVELS.map((level) => (
        <div key={level}>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-stone-500">
            {t("level")} {level}
          </h2>
          <div className="space-y-2">
            {LEVEL_MODULES[level].map((code) => (
              <ModuleSection key={code} moduleCode={code} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
