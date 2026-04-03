"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getAdminSettings,
  updateSetting,
  resetSetting,
  resetSettingCategory,
  type SettingsByCategory,
  type PlatformSetting,
} from "@/lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  quiz: "Quiz & Assessment",
  progress: "Progress & Unlocking",
  flashcards: "Flashcards (FSRS)",
  placement: "Placement Test",
  auth: "Auth & Security",
  rate_limiting: "Rate Limiting",
  ai: "AI & Content Generation",
  tutor: "AI Tutor",
  pagination: "Pagination",
};

export function SettingsClient() {
  const t = useTranslations("Admin.settings");
  const [categories, setCategories] = useState<SettingsByCategory[]>([]);
  const [activeTab, setActiveTab] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => { loadSettings(); }, []);

  async function loadSettings() {
    try {
      const data = await getAdminSettings();
      setCategories(data);
      if (data.length > 0 && !activeTab) setActiveTab(data[0].category);
    } catch { setToast("Failed to load settings"); }
    finally { setLoading(false); }
  }

  async function handleSave(key: string, value: unknown) {
    setSaving(key);
    try { await updateSetting(key, value); await loadSettings(); showToast(t("saved")); }
    catch (err) { showToast(err instanceof Error ? err.message : "Error saving"); }
    finally { setSaving(null); }
  }

  async function handleReset(key: string) {
    setSaving(key);
    try { await resetSetting(key); await loadSettings(); showToast(t("resetDone")); }
    catch { showToast("Error resetting"); }
    finally { setSaving(null); }
  }

  async function handleResetCategory(category: string) {
    if (!confirm(t("resetConfirm"))) return;
    setSaving(category);
    try {
      const res = await resetSettingCategory(category);
      await loadSettings();
      showToast(t("categoryResetDone", { count: res.reset_count }));
    } catch { showToast("Error resetting category"); }
    finally { setSaving(null); }
  }

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  if (loading) return (
    <div className="flex items-center justify-center p-12">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
    </div>
  );

  const activeCategory = categories.find((c) => c.category === activeTab);

  return (
    <div className="px-4 py-6 md:px-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground shadow-lg">
          {toast}
        </div>
      )}
      <div className="mb-6 flex flex-wrap gap-2">
        {categories.map((cat) => (
          <button key={cat.category} onClick={() => setActiveTab(cat.category)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === cat.category
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            {CATEGORY_LABELS[cat.category] || cat.category}
          </button>
        ))}
      </div>
      {activeCategory && (
        <div className="space-y-1">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              {CATEGORY_LABELS[activeCategory.category] || activeCategory.category}
            </h2>
            <button onClick={() => handleResetCategory(activeCategory.category)}
              className="rounded-md border border-destructive/30 px-3 py-1 text-xs text-destructive hover:bg-destructive/10"
              disabled={saving !== null}
            >
              {t("resetCategory")}
            </button>
          </div>
          <div className="divide-y rounded-lg border">
            {activeCategory.settings.map((s) => (
              <SettingRow key={s.key} setting={s} saving={saving === s.key}
                onSave={handleSave} onReset={handleReset} t={t} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SettingRow({ setting, saving, onSave, onReset, t }: {
  setting: PlatformSetting; saving: boolean;
  onSave: (key: string, value: unknown) => void;
  onReset: (key: string) => void;
  t: (key: string) => string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(
    typeof setting.value === "object" ? JSON.stringify(setting.value, null, 2) : String(setting.value)
  );

  useEffect(() => {
    setDraft(typeof setting.value === "object" ? JSON.stringify(setting.value, null, 2) : String(setting.value));
    setEditing(false);
  }, [setting.value]);

  function handleSubmit() {
    let parsed: unknown;
    if (setting.value_type === "integer") parsed = parseInt(draft, 10);
    else if (setting.value_type === "float") parsed = parseFloat(draft);
    else if (setting.value_type === "boolean") parsed = draft === "true";
    else if (setting.value_type === "json") { try { parsed = JSON.parse(draft); } catch { return; } }
    else parsed = draft;
    onSave(setting.key, parsed);
  }

  const rules = setting.validation_rules;

  return (
    <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{setting.label}</span>
          {!setting.is_default && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">{t("modified")}</span>}
          {setting.is_sensitive && <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">{t("sensitive")}</span>}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">{setting.description}</p>
        {rules && <p className="text-xs text-muted-foreground">
          {rules.min != null && `Min: ${rules.min}`}{rules.min != null && rules.max != null && " | "}{rules.max != null && `Max: ${rules.max}`}
        </p>}
        <p className="text-xs text-muted-foreground">{t("defaultValue")}: {typeof setting.default_value === "object" ? JSON.stringify(setting.default_value) : String(setting.default_value)}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {editing ? (<>
          {setting.value_type === "json" ? (
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
              className="w-64 rounded border bg-background px-2 py-1 text-sm font-mono" rows={4} />
          ) : setting.value_type === "boolean" ? (
            <select value={draft} onChange={(e) => setDraft(e.target.value)}
              className="rounded border bg-background px-2 py-1 text-sm">
              <option value="true">true</option><option value="false">false</option>
            </select>
          ) : (
            <input type={setting.value_type === "integer" || setting.value_type === "float" ? "number" : "text"}
              step={setting.value_type === "float" ? "0.1" : "1"}
              min={rules?.min} max={rules?.max} value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-28 rounded border bg-background px-2 py-1 text-sm" />
          )}
          <button onClick={handleSubmit} disabled={saving}
            className="rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {saving ? "..." : t("save")}
          </button>
          <button onClick={() => setEditing(false)} className="rounded border px-3 py-1 text-xs hover:bg-muted">Cancel</button>
        </>) : (<>
          <code className="rounded bg-muted px-2 py-1 text-sm">
            {typeof setting.value === "object" ? JSON.stringify(setting.value) : String(setting.value)}
          </code>
          <button onClick={() => setEditing(true)} className="rounded border px-3 py-1 text-xs hover:bg-muted">Edit</button>
          {!setting.is_default && (
            <button onClick={() => onReset(setting.key)} disabled={saving}
              className="rounded border border-destructive/30 px-3 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50">
              {t("reset")}
            </button>
          )}
        </>)}
      </div>
    </div>
  );
}
