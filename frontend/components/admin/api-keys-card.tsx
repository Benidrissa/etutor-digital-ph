"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getApiKeys,
  updateApiKey,
  type ApiKeyStatus,
} from "@/lib/api";

// Display metadata per provider. `field` is the form input name; the order
// here is the render order. Placeholders show the expected key format.
const PROVIDERS: { id: string; label: string; placeholder: string }[] = [
  { id: "anthropic", label: "Anthropic", placeholder: "sk-ant-..." },
  { id: "openai", label: "OpenAI", placeholder: "sk-..." },
  { id: "google", label: "Google", placeholder: "AIza..." },
  { id: "resend", label: "Resend", placeholder: "re_..." },
  { id: "moonshot", label: "Moonshot", placeholder: "sk-..." },
];

export function ApiKeysCard() {
  const t = useTranslations("Admin.apiKeys");
  const [statuses, setStatuses] = useState<ApiKeyStatus[]>([]);
  const [encryptionOk, setEncryptionOk] = useState(true);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const data = await getApiKeys();
      setStatuses(data.providers);
      setEncryptionOk(data.encryption_configured);
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }

  const statusOf = (id: string) => statuses.find((s) => s.provider === id);

  async function handleSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    // Only send providers whose input was actually filled — blank means "keep".
    const changed = PROVIDERS.map((p) => ({
      id: p.id,
      value: String(form.get(p.id) ?? "").trim(),
    })).filter((p) => p.value !== "");

    if (changed.length === 0) {
      setEditing(false);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      let latest = { providers: statuses, encryption_configured: encryptionOk };
      for (const c of changed) {
        latest = await updateApiKey(c.id, c.value);
      }
      setStatuses(latest.providers);
      setEncryptionOk(latest.encryption_configured);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border p-4 md:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("title")}</h2>
        {!editing && !loading && (
          <button
            onClick={() => {
              setError(null);
              setEditing(true);
            }}
            className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted"
          >
            {t("updateKeys")}
          </button>
        )}
      </div>

      <p className="mb-4 text-sm text-muted-foreground">{t("description")}</p>

      {!encryptionOk && (
        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {t("encryptionMissing")}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      ) : editing ? (
        <form onSubmit={handleSave} className="space-y-3">
          {PROVIDERS.map((p) => {
            const st = statusOf(p.id);
            return (
              <div
                key={p.id}
                className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-4"
              >
                <label
                  htmlFor={`api-key-${p.id}`}
                  className="w-40 shrink-0 text-sm font-medium"
                >
                  {p.label}
                  {st?.is_set && (
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {t("configured")}
                    </span>
                  )}
                </label>
                <input
                  id={`api-key-${p.id}`}
                  name={p.id}
                  type="password"
                  autoComplete="off"
                  placeholder={p.placeholder}
                  className="flex-1 rounded border bg-background px-2 py-1.5 text-sm"
                />
              </div>
            );
          })}
          <p className="text-xs text-muted-foreground">{t("blankHint")}</p>
          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={saving}
              className="rounded bg-primary px-4 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {saving ? t("saving") : t("save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
              className="rounded border px-4 py-1.5 text-sm hover:bg-muted"
            >
              {t("cancel")}
            </button>
          </div>
        </form>
      ) : (
        <div className="divide-y rounded-lg border">
          {PROVIDERS.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between px-3 py-2.5"
            >
              <span className="text-sm text-muted-foreground">{p.label}</span>
              <KeyStatusBadge status={statusOf(p.id)} t={t} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KeyStatusBadge({
  status,
  t,
}: {
  status: ApiKeyStatus | undefined;
  t: (key: string) => string;
}) {
  if (status?.decrypt_error) {
    return (
      <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
        {t("undecryptable")}
      </span>
    );
  }
  if (status?.is_set) {
    return (
      <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
        {t("set")}
      </span>
    );
  }
  if (status?.env_fallback) {
    return (
      <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
        {t("provisioned")}
      </span>
    );
  }
  return (
    <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
      {t("notSet")}
    </span>
  );
}
