"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Trash2, Save, Users, Settings } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { LoadingSpinner } from "@/components/ui/loading-spinner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("access_token") ?? "";
}

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${getToken()}`,
  };
}

interface GlobalLimitResponse {
  daily_limit: number;
}

interface UserUsage {
  user_id: string;
  usage_today: number;
  effective_limit: number;
  override_limit: number | null;
}

interface UsageListResponse {
  users: UserUsage[];
  global_limit: number;
}

async function fetchGlobalLimit(): Promise<GlobalLimitResponse> {
  const res = await fetch(`${API_BASE}/api/v1/admin/rate-limits/global`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function updateGlobalLimit(limit: number): Promise<GlobalLimitResponse> {
  const res = await fetch(`${API_BASE}/api/v1/admin/rate-limits/global`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify({ daily_limit: limit }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function fetchUserUsages(): Promise<UsageListResponse> {
  const res = await fetch(`${API_BASE}/api/v1/admin/rate-limits/users`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function setUserOverride(userId: string, limit: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/admin/rate-limits/users/${userId}`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify({ daily_limit: limit }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
}

async function deleteUserOverride(userId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/admin/rate-limits/users/${userId}/override`,
    { method: "DELETE", headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`${res.status}`);
}

async function resetUserUsage(userId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/admin/rate-limits/users/${userId}/reset`,
    { method: "POST", headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`${res.status}`);
}

export function AdminRateLimitsClient() {
  const t = useTranslations("AdminRateLimits");
  const qc = useQueryClient();

  const [globalInput, setGlobalInput] = useState<string>("");
  const [overrideInputs, setOverrideInputs] = useState<Record<string, string>>({});
  const [newUserId, setNewUserId] = useState("");
  const [newUserLimit, setNewUserLimit] = useState("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const { data: globalData, isLoading: globalLoading, error: globalError } = useQuery({
    queryKey: ["admin", "rate-limits", "global"],
    queryFn: fetchGlobalLimit,
  });

  const { data: usagesData, isLoading: usagesLoading } = useQuery({
    queryKey: ["admin", "rate-limits", "users"],
    queryFn: fetchUserUsages,
    refetchInterval: 30_000,
  });

  const globalMutation = useMutation({
    mutationFn: (limit: number) => updateGlobalLimit(limit),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin", "rate-limits"] });
      setGlobalInput("");
      setSuccessMsg(t("globalLimitUpdated", { limit: data.daily_limit }));
      setTimeout(() => setSuccessMsg(null), 3000);
    },
  });

  const overrideMutation = useMutation({
    mutationFn: ({ userId, limit }: { userId: string; limit: number }) =>
      setUserOverride(userId, limit),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "rate-limits", "users"] });
      setNewUserId("");
      setNewUserLimit("");
      setOverrideInputs({});
    },
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (userId: string) => deleteUserOverride(userId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["admin", "rate-limits", "users"] }),
  });

  const resetMutation = useMutation({
    mutationFn: (userId: string) => resetUserUsage(userId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["admin", "rate-limits", "users"] }),
  });

  function handleGlobalSave() {
    const parsed = parseInt(globalInput, 10);
    if (!isNaN(parsed) && parsed >= 1 && parsed <= 10000) {
      globalMutation.mutate(parsed);
    }
  }

  function handleSetOverride(userId: string) {
    const val = overrideInputs[userId] ?? "";
    const parsed = parseInt(val, 10);
    if (!isNaN(parsed) && parsed >= 1 && parsed <= 10000) {
      overrideMutation.mutate({ userId, limit: parsed });
    }
  }

  function handleNewUserOverride() {
    const parsed = parseInt(newUserLimit, 10);
    if (newUserId.trim() && !isNaN(parsed) && parsed >= 1 && parsed <= 10000) {
      overrideMutation.mutate({ userId: newUserId.trim(), limit: parsed });
    }
  }

  if (globalError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{t("accessDenied")}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      {successMsg && (
        <Alert>
          <AlertDescription>{successMsg}</AlertDescription>
        </Alert>
      )}

      {/* Global Limit Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            {t("globalLimitTitle")}
          </CardTitle>
          <CardDescription>{t("globalLimitDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {globalLoading ? (
            <LoadingSpinner />
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="text-base px-3 py-1">
                  {t("currentLimit", { limit: globalData?.daily_limit ?? "—" })}
                </Badge>
              </div>
              <div className="flex gap-2 max-w-xs">
                <div className="flex-1">
                  <Label htmlFor="global-limit-input" className="sr-only">
                    {t("newLimit")}
                  </Label>
                  <Input
                    id="global-limit-input"
                    type="number"
                    min={1}
                    max={10000}
                    placeholder={t("newLimitPlaceholder")}
                    value={globalInput}
                    onChange={(e) => setGlobalInput(e.target.value)}
                    className="min-h-11"
                  />
                </div>
                <Button
                  onClick={handleGlobalSave}
                  disabled={globalMutation.isPending || !globalInput}
                  className="min-h-11 min-w-11"
                >
                  {globalMutation.isPending ? (
                    <LoadingSpinner className="h-4 w-4" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  <span className="ml-2">{t("save")}</span>
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Per-User Overrides + Usage Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            {t("userOverridesTitle")}
          </CardTitle>
          <CardDescription>{t("userOverridesDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Add new override */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">{t("addOverride")}</Label>
            <div className="flex gap-2 flex-wrap">
              <Input
                placeholder={t("userIdPlaceholder")}
                value={newUserId}
                onChange={(e) => setNewUserId(e.target.value)}
                className="min-h-11 flex-1 min-w-[200px]"
              />
              <Input
                type="number"
                min={1}
                max={10000}
                placeholder={t("limitPlaceholder")}
                value={newUserLimit}
                onChange={(e) => setNewUserLimit(e.target.value)}
                className="min-h-11 w-32"
              />
              <Button
                onClick={handleNewUserOverride}
                disabled={overrideMutation.isPending || !newUserId || !newUserLimit}
                className="min-h-11"
              >
                {overrideMutation.isPending ? (
                  <LoadingSpinner className="h-4 w-4" />
                ) : (
                  t("setOverride")
                )}
              </Button>
            </div>
          </div>

          <Separator />

          {/* Usage table */}
          {usagesLoading ? (
            <LoadingSpinner />
          ) : !usagesData?.users.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              {t("noActiveUsers")}
            </p>
          ) : (
            <div className="space-y-3">
              <Label className="text-sm font-medium">{t("activeUsers")}</Label>
              <div className="rounded-md border divide-y">
                {usagesData.users.map((user) => (
                  <UserRow
                    key={user.user_id}
                    user={user}
                    overrideInput={overrideInputs[user.user_id] ?? ""}
                    onOverrideChange={(val) =>
                      setOverrideInputs((prev) => ({ ...prev, [user.user_id]: val }))
                    }
                    onSaveOverride={() => handleSetOverride(user.user_id)}
                    onDeleteOverride={() => deleteOverrideMutation.mutate(user.user_id)}
                    onReset={() => resetMutation.mutate(user.user_id)}
                    isSaving={overrideMutation.isPending}
                    isDeleting={deleteOverrideMutation.isPending}
                    isResetting={resetMutation.isPending}
                  />
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

interface UserRowProps {
  user: UserUsage;
  overrideInput: string;
  onOverrideChange: (val: string) => void;
  onSaveOverride: () => void;
  onDeleteOverride: () => void;
  onReset: () => void;
  isSaving: boolean;
  isDeleting: boolean;
  isResetting: boolean;
}

function UserRow({
  user,
  overrideInput,
  onOverrideChange,
  onSaveOverride,
  onDeleteOverride,
  onReset,
  isSaving,
  isDeleting,
  isResetting,
}: UserRowProps) {
  const t = useTranslations("AdminRateLimits");
  const usagePercent =
    user.effective_limit > 0
      ? Math.min(100, Math.round((user.usage_today / user.effective_limit) * 100))
      : 0;

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-mono truncate">{user.user_id}</p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-xs text-muted-foreground">
              {t("usageToday", {
                used: user.usage_today,
                limit: user.effective_limit,
              })}
            </span>
            {user.override_limit !== null && (
              <Badge variant="outline" className="text-xs">
                {t("hasOverride", { limit: user.override_limit })}
              </Badge>
            )}
            <Badge
              variant={usagePercent >= 90 ? "destructive" : "secondary"}
              className="text-xs"
            >
              {usagePercent}%
            </Badge>
          </div>
        </div>

        <div className="flex gap-1 flex-shrink-0">
          <Button
            size="sm"
            variant="outline"
            onClick={onReset}
            disabled={isResetting}
            className="min-h-9 min-w-9"
            title={t("resetUsage")}
          >
            {isResetting ? (
              <LoadingSpinner className="h-3 w-3" />
            ) : (
              <RotateCcw className="h-3 w-3" />
            )}
          </Button>
          {user.override_limit !== null && (
            <Button
              size="sm"
              variant="outline"
              onClick={onDeleteOverride}
              disabled={isDeleting}
              className="min-h-9 min-w-9 text-destructive hover:text-destructive"
              title={t("removeOverride")}
            >
              {isDeleting ? (
                <LoadingSpinner className="h-3 w-3" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Inline override setter */}
      <div className="flex gap-2">
        <Input
          type="number"
          min={1}
          max={10000}
          placeholder={t("limitPlaceholder")}
          value={overrideInput}
          onChange={(e) => onOverrideChange(e.target.value)}
          className="h-8 text-sm flex-1"
        />
        <Button
          size="sm"
          onClick={onSaveOverride}
          disabled={isSaving || !overrideInput}
          className="h-8"
        >
          {isSaving ? <LoadingSpinner className="h-3 w-3" /> : t("setOverride")}
        </Button>
      </div>
    </div>
  );
}
