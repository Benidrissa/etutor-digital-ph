"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ChevronDown, ChevronUp, RotateCcw, Save } from "lucide-react";
import type { PlatformSetting } from "@/lib/api";

const TEMPLATE_VARIABLES = [
  { name: "course_title", descKey: "varCourseTitle" },
  { name: "course_description", descKey: "varCourseDescription" },
  { name: "course_domain", descKey: "varCourseDomain" },
  { name: "module_title", descKey: "varModuleTitle" },
  { name: "unit_title", descKey: "varUnitTitle" },
  { name: "country", descKey: "varCountry" },
  { name: "language", descKey: "varLanguage" },
  { name: "level", descKey: "varLevel" },
  { name: "bloom_level", descKey: "varBloomLevel" },
  { name: "syllabus_context", descKey: "varSyllabusContext" },
] as const;

interface PromptEditorProps {
  setting: PlatformSetting;
  saving: boolean;
  onSave: (key: string, value: unknown) => void;
  onReset: (key: string) => void;
}

export function PromptEditor({ setting, saving, onSave, onReset }: PromptEditorProps) {
  const t = useTranslations("Admin.settings");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState(String(setting.value));
  const [prevValue, setPrevValue] = useState(setting.value);
  const [showDefault, setShowDefault] = useState(false);

  if (setting.value !== prevValue) {
    setPrevValue(setting.value);
    setDraft(String(setting.value));
  }

  function insertVariable(varName: string) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const token = `{${varName}}`;
    const next = draft.slice(0, start) + token + draft.slice(end);
    setDraft(next);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(start + token.length, start + token.length);
    });
  }

  function handleSave() {
    onSave(setting.key, draft);
  }

  function handleReset() {
    onReset(setting.key);
  }

  const isDirty = draft !== String(setting.value);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-sm">{setting.label}</span>
          {!setting.is_default && (
            <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-700 text-xs">
              {t("modified")}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{setting.description}</p>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-muted-foreground">{t("promptVariables")}</p>
        <div className="flex flex-wrap gap-1.5">
          {TEMPLATE_VARIABLES.map((v) => (
            <button
              key={v.name}
              type="button"
              title={t(v.descKey)}
              onClick={() => insertVariable(v.name)}
              className="inline-flex items-center rounded-md border border-teal-200 bg-teal-50 px-2 py-1 font-mono text-xs text-teal-700 transition-colors hover:bg-teal-100 active:bg-teal-200 min-h-[44px] md:min-h-0"
            >
              {`{${v.name}}`}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{t("promptVariablesHint")}</p>
      </div>

      <div className="flex flex-col gap-2">
        <Textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setEditing(true); }}
          rows={18}
          className="font-mono text-sm resize-y min-h-[200px]"
          spellCheck={false}
          aria-label={setting.label}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          onClick={handleSave}
          disabled={saving || !isDirty}
          className="min-h-[44px] md:min-h-9"
        >
          <Save className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {saving ? "..." : t("save")}
        </Button>
        {!setting.is_default && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleReset}
            disabled={saving}
            className="min-h-[44px] md:min-h-9 border-destructive/30 text-destructive hover:bg-destructive/10"
          >
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            {t("reset")}
          </Button>
        )}
        {isDirty && (
          <button
            type="button"
            onClick={() => setDraft(String(setting.value))}
            className="text-xs text-muted-foreground underline hover:text-foreground"
          >
            {t("discardChanges")}
          </button>
        )}
      </div>

      <div className="rounded-md border border-border">
        <button
          type="button"
          onClick={() => setShowDefault((p) => !p)}
          className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors"
          aria-expanded={showDefault}
        >
          <span>{t("promptShowDefault")}</span>
          {showDefault ? (
            <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
        {showDefault && (
          <div className="border-t border-border px-3 py-3">
            <pre className="whitespace-pre-wrap font-mono text-xs text-muted-foreground break-words">
              {String(setting.default_value)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
