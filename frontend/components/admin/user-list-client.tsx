"use client";

import { useState, useCallback, useTransition, useRef } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Download, Upload, UserPlus, MoreVertical, UserCheck, UserX, ShieldCheck, ShieldOff, Shield, ChevronLeft, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { apiFetch, API_BASE } from "@/lib/api";
import { authClient } from "@/lib/auth";

interface AdminUser {
  id: string;
  email: string | null;
  name: string;
  preferred_language: string;
  country: string | null;
  professional_role: string | null;
  current_level: number;
  streak_days: number;
  avatar_url: string | null;
  last_active: string;
  created_at: string;
  role: "user" | "expert" | "admin";
  is_active: boolean;
  phone_number: string | null;
}

type PendingAction =
  | { type: "deactivate"; user: AdminUser }
  | { type: "reactivate"; user: AdminUser }
  | { type: "promote"; user: AdminUser; newRole: "expert" | "admin" | "user" };

const PAGE_SIZES = [10, 25, 50, 100] as const;

function buildFilterQuery(params: {
  search: string;
  country: string;
  level: string;
  role: string;
  isActive: string;
}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.country) query.set("country", params.country);
  if (params.level) query.set("level", params.level);
  if (params.role) query.set("role", params.role);
  if (params.isActive) query.set("is_active", params.isActive);
  return query;
}

function useAdminUsers(params: {
  search: string;
  country: string;
  level: string;
  role: string;
  isActive: string;
  offset: number;
  limit: number;
}) {
  const query = buildFilterQuery(params);
  query.set("offset", String(params.offset));
  query.set("limit", String(params.limit));

  return useQuery<AdminUser[]>({
    queryKey: ["admin", "users", params],
    queryFn: () => apiFetch<AdminUser[]>(`/api/v1/admin/users?${query.toString()}`),
  });
}

function useAdminUserCount(params: {
  search: string;
  country: string;
  level: string;
  role: string;
  isActive: string;
}) {
  const query = buildFilterQuery(params);

  return useQuery<{ count: number }>({
    queryKey: ["admin", "users", "count", params],
    queryFn: () => apiFetch<{ count: number }>(`/api/v1/admin/users/count?${query.toString()}`),
  });
}

export function UserListClient() {
  const t = useTranslations("Admin.users");
  const tRoles = useTranslations("Roles");
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [, startTransition] = useTransition();

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [country, setCountry] = useState("");
  const [level, setLevel] = useState("");
  const [role, setRole] = useState("");
  const [isActive, setIsActive] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(50);
  // px widths per column [name, role, contact, country, level, created, actions]; undefined = auto
  const [colWidths, setColWidths] = useState<(number | undefined)[]>(
    [undefined, 112, 192, 112, 96, 112, 48]
  );
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ created: number; skipped: number; errors: { row: number; error: string }[] } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const searchTimeout = useCallback(
    (value: string) => {
      setSearch(value);
      setOffset(0);
      const timer = setTimeout(() => setDebouncedSearch(value), 400);
      return () => clearTimeout(timer);
    },
    []
  );

  const filterParams = { search: debouncedSearch, country, level, role, isActive };

  const { data: users, isLoading, error } = useAdminUsers({ ...filterParams, offset, limit: pageSize });
  const { data: countData } = useAdminUserCount(filterParams);

  const statusMutation = useMutation({
    mutationFn: ({ userId, is_active }: { userId: string; is_active: boolean }) =>
      apiFetch(`/api/v1/admin/users/${userId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ is_active }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: (err) => {
      console.error("Admin status action failed:", err);
      setActionError(t("actionError"));
    },
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role: newRole }: { userId: string; role: string }) =>
      apiFetch(`/api/v1/admin/users/${userId}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role: newRole }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setPendingAction(null);
      setActionError(null);
    },
    onError: (err) => {
      console.error("Admin role action failed:", err);
      setActionError(t("actionError"));
    },
  });

  const handleConfirmAction = () => {
    if (!pendingAction) return;
    if (pendingAction.type === "deactivate") {
      statusMutation.mutate({ userId: pendingAction.user.id, is_active: false });
    } else if (pendingAction.type === "reactivate") {
      statusMutation.mutate({ userId: pendingAction.user.id, is_active: true });
    } else if (pendingAction.type === "promote") {
      roleMutation.mutate({ userId: pendingAction.user.id, role: pendingAction.newRole });
    }
  };

  const handleExport = async () => {
    const query = new URLSearchParams();
    if (debouncedSearch) query.set("search", debouncedSearch);
    if (country) query.set("country", country);
    if (level) query.set("level", level);
    if (role) query.set("role", role);
    if (isActive) query.set("is_active", isActive);

    try {
      const token = await authClient.getValidToken();
      const response = await fetch(
        `${API_BASE}/api/v1/admin/users/export/csv?${query.toString()}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "users_export.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setActionError(t("actionError"));
    }
  };

  const handleCreateUser = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setCreateLoading(true);
    setActionError(null);
    const form = new FormData(e.currentTarget);
    try {
      await apiFetch("/api/v1/admin/users", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          identifier: form.get("identifier"),
          password: form.get("password"),
          role: form.get("role") || "user",
          preferred_language: form.get("preferred_language") || "fr",
          country: form.get("country") || undefined,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setShowCreateForm(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t("actionError"));
    } finally {
      setCreateLoading(false);
    }
  };

  const handleImportCsv = async (file: File) => {
    setImportLoading(true);
    setImportResult(null);
    setActionError(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const token = await authClient.getValidToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/users/import/csv`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Import failed: ${res.status}`);
      }
      const result = await res.json();
      setImportResult(result);
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t("actionError"));
    } finally {
      setImportLoading(false);
    }
  };

  const downloadTemplate = () => {
    const csv = "name,identifier,password,role,language,country\nJohn Doe,john@example.com,password123,user,en,senegal\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "users_import_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const startResize = (e: React.MouseEvent, colIndex: number) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = colWidths[colIndex] ?? 96;
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX;
      setColWidths((prev) => {
        const next = [...prev];
        next[colIndex] = Math.max(60, startWidth + delta);
        return next;
      });
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const confirmTitle =
    pendingAction?.type === "deactivate"
      ? t("confirmDeactivate")
      : pendingAction?.type === "reactivate"
        ? t("confirmReactivate")
        : t("confirmPromote");

  const confirmDesc =
    pendingAction?.type === "deactivate"
      ? t("confirmDeactivateDesc")
      : pendingAction?.type === "reactivate"
        ? t("confirmReactivateDesc")
        : pendingAction?.type === "promote"
          ? t("confirmPromoteDesc", { role: tRoles(pendingAction.newRole) })
          : "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:flex-wrap">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            className="pl-9 min-h-11"
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(e) => searchTimeout(e.target.value)}
            aria-label={t("searchPlaceholder")}
          />
        </div>

        {/* Free-text country filter — the former hardcoded W. African list
            was tenant-inappropriate for the generalised platform (#1620). */}
        <input
          type="text"
          className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={country}
          onChange={(e) => { setCountry(e.target.value); setOffset(0); }}
          placeholder={t("filterCountry")}
          aria-label={t("filterCountry")}
        />

        <select
          className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={level}
          onChange={(e) => { setLevel(e.target.value); setOffset(0); }}
          aria-label={t("filterLevel")}
        >
          <option value="">{t("allLevels")}</option>
          {[1, 2, 3, 4].map((l) => (
            <option key={l} value={String(l)}>{t("level", { level: l })}</option>
          ))}
        </select>

        <select
          className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={role}
          onChange={(e) => { setRole(e.target.value); setOffset(0); }}
          aria-label={t("filterRole")}
        >
          <option value="">{t("allRoles")}</option>
          <option value="user">{tRoles("user")}</option>
          <option value="expert">{tRoles("expert")}</option>
          <option value="sub_admin">{tRoles("sub_admin")}</option>
          <option value="admin">{tRoles("admin")}</option>
        </select>

        <select
          className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={isActive}
          onChange={(e) => { setIsActive(e.target.value); setOffset(0); }}
          aria-label={t("filterStatus")}
        >
          <option value="">{t("allStatuses")}</option>
          <option value="true">{t("active")}</option>
          <option value="false">{t("inactive")}</option>
        </select>

        <Button
          variant="outline"
          className="min-h-11 gap-2 shrink-0"
          onClick={handleExport}
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          {t("exportCsv")}
        </Button>

        <Button
          variant="outline"
          className="min-h-11 gap-2 shrink-0"
          onClick={() => setShowImport(true)}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          {t("importCsv")}
        </Button>

        <Button
          className="min-h-11 gap-2 shrink-0"
          onClick={() => setShowCreateForm(true)}
        >
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          {t("addUser")}
        </Button>
      </div>

      {actionError && (
        <p className="text-sm text-destructive" role="alert">{actionError}</p>
      )}

      {isLoading && (
        <p className="text-muted-foreground text-sm py-8 text-center">{t("loading")}</p>
      )}

      {error && (
        <p className="text-destructive text-sm py-8 text-center" role="alert">{t("error")}</p>
      )}

      {users && users.length === 0 && !isLoading && (
        <div className="py-12 text-center">
          <p className="text-muted-foreground font-medium">{t("noUsersFound")}</p>
          <p className="text-sm text-muted-foreground mt-1">{t("noUsersDescription")}</p>
        </div>
      )}

      {users && users.length > 0 && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {countData
              ? t("userCountTotal", { count: countData.count })
              : t("userCount", { count: users.length })}
          </p>
          <div className="overflow-x-auto">
            <table className="table-fixed w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground text-left select-none">
                  <th className="pb-2 pr-4 relative" style={colWidths[0] !== undefined ? { width: colWidths[0] } : undefined}>
                    {t("name")}
                  </th>
                  <th className="pb-2 pr-4 relative" style={{ width: colWidths[1] }}>
                    {t("role")}
                    <span className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-border" onMouseDown={(e) => startResize(e, 1)} />
                  </th>
                  <th className="pb-2 pr-4 relative" style={{ width: colWidths[2] }}>
                    {t("contact")}
                    <span className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-border" onMouseDown={(e) => startResize(e, 2)} />
                  </th>
                  <th className="pb-2 pr-4 relative" style={{ width: colWidths[3] }}>
                    {t("country")}
                    <span className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-border" onMouseDown={(e) => startResize(e, 3)} />
                  </th>
                  <th className="pb-2 pr-4 relative" style={{ width: colWidths[4] }}>
                    {t("levelHeader")}
                    <span className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-border" onMouseDown={(e) => startResize(e, 4)} />
                  </th>
                  <th className="pb-2 pr-4 relative" style={{ width: colWidths[5] }}>
                    {t("createdAt")}
                    <span className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-border" onMouseDown={(e) => startResize(e, 5)} />
                  </th>
                  <th className="pb-2" style={{ width: colWidths[6] }} />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <UserRow
                    key={user.id}
                    user={user}
                    onDeactivate={(u) => setPendingAction({ type: "deactivate", user: u })}
                    onReactivate={(u) => setPendingAction({ type: "reactivate", user: u })}
                    onPromote={(u, r) => setPendingAction({ type: "promote", user: u, newRole: r })}
                    onViewDetails={(u) =>
                      startTransition(() =>
                        router.push(`/${locale}/admin/users/${u.id}`)
                      )
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
          {countData && countData.count > 0 && (
            <div className="flex items-center justify-between gap-3 pt-2">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Rows</span>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setOffset(0); }}
                  className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                  aria-label="Rows per page"
                >
                  {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="min-h-11 min-w-11 gap-2"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - pageSize))}
                  aria-label={t("prevPage")}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                  <span className="hidden sm:inline">{t("prevPage")}</span>
                </Button>
                <span className="text-sm text-muted-foreground">
                  {t("pageIndicator", {
                    page: Math.floor(offset / pageSize) + 1,
                    total: Math.ceil(countData.count / pageSize),
                  })}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="min-h-11 min-w-11 gap-2"
                  disabled={offset + pageSize >= countData.count}
                  onClick={() => setOffset(offset + pageSize)}
                  aria-label={t("nextPage")}
                >
                  <span className="hidden sm:inline">{t("nextPage")}</span>
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Confirm action dialog */}
      <AlertDialog open={pendingAction !== null} onOpenChange={(open) => !open && setPendingAction(null)}>
        <AlertDialogContent>
          <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
          <AlertDialogDescription>{confirmDesc}</AlertDialogDescription>
          <div className="flex justify-end gap-3 mt-4">
            <AlertDialogCancel onClick={() => setPendingAction(null)}>
              {t("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmAction}
              disabled={statusMutation.isPending || roleMutation.isPending}
            >
              {t("confirm")}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      {/* Create user dialog */}
      <AlertDialog open={showCreateForm} onOpenChange={setShowCreateForm}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("createUser")}</AlertDialogTitle>
          <AlertDialogDescription>{t("createUserDesc")}</AlertDialogDescription>
          <form onSubmit={handleCreateUser} className="space-y-3 mt-2">
            <Input name="name" placeholder={t("name")} required minLength={2} className="min-h-11" />
            <Input name="identifier" placeholder={t("identifier")} required className="min-h-11" />
            <Input name="password" type="password" placeholder={t("password")} required minLength={6} className="min-h-11" />
            <select name="role" className="w-full min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm">
              <option value="user">{tRoles("user")}</option>
              <option value="expert">{tRoles("expert")}</option>
            </select>
            <select name="preferred_language" className="w-full min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm">
              <option value="fr">Français</option>
              <option value="en">English</option>
            </select>
            <div className="flex justify-end gap-3 mt-4">
              <AlertDialogCancel type="button" onClick={() => setShowCreateForm(false)}>
                {t("cancel")}
              </AlertDialogCancel>
              <Button type="submit" disabled={createLoading}>
                {createLoading ? t("creating") : t("createUser")}
              </Button>
            </div>
          </form>
        </AlertDialogContent>
      </AlertDialog>

      {/* Import CSV dialog */}
      <AlertDialog open={showImport} onOpenChange={(open) => { if (!open) { setShowImport(false); setImportResult(null); } }}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("importTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("importDesc")}</AlertDialogDescription>
          <div className="space-y-3 mt-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="w-full text-sm"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImportCsv(file);
              }}
            />
            {importLoading && <p className="text-sm text-muted-foreground">{t("importing")}</p>}
            {importResult && (
              <div className="text-sm space-y-1">
                <p className="font-medium">{t("importResults", { created: importResult.created, skipped: importResult.skipped, errors: importResult.errors.length })}</p>
                {importResult.errors.length > 0 && (
                  <ul className="text-destructive text-xs space-y-0.5">
                    {importResult.errors.slice(0, 10).map((e, i) => (
                      <li key={i}>Row {e.row}: {e.error}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <div className="flex justify-between mt-4">
              <Button variant="link" size="sm" className="px-0" onClick={downloadTemplate}>
                {t("downloadTemplate")}
              </Button>
              <AlertDialogCancel onClick={() => { setShowImport(false); setImportResult(null); }}>
                {t("cancel")}
              </AlertDialogCancel>
            </div>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function UserRow({
  user,
  onDeactivate,
  onReactivate,
  onPromote,
  onViewDetails,
}: {
  user: AdminUser;
  onDeactivate: (u: AdminUser) => void;
  onReactivate: (u: AdminUser) => void;
  onPromote: (u: AdminUser, role: "expert" | "admin" | "user") => void;
  onViewDetails: (u: AdminUser) => void;
}) {
  const t = useTranslations("Admin.users");
  const tRoles = useTranslations("Roles");

  const roleVariant = user.role === "admin" ? "destructive" : user.role === "expert" ? "secondary" : "outline";

  return (
    <tr className="border-b last:border-0 align-middle hover:bg-muted/40 transition-colors">
      <td className="py-2 pr-4">
        <button
          className="flex items-center gap-2 text-left font-medium hover:underline"
          onClick={() => onViewDetails(user)}
          aria-label={t("viewDetails")}
        >
          {user.name}
          {!user.is_active && (
            <Badge variant="destructive" className="text-xs">{t("inactive")}</Badge>
          )}
        </button>
      </td>
      <td className="py-2 pr-4">
        <Badge variant={roleVariant}>{tRoles(user.role)}</Badge>
      </td>
      <td className="py-2 pr-4">
        {user.email && <p className="truncate text-muted-foreground text-xs">{user.email}</p>}
        {user.phone_number && <p className="truncate text-muted-foreground text-xs">{user.phone_number}</p>}
      </td>
      <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap text-xs">{user.country ?? "—"}</td>
      <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap text-xs">{t("level", { level: user.current_level })}</td>
      <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap text-xs">{user.created_at.slice(0, 10)}</td>
      <td className="py-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="ghost"
                size="sm"
                className="min-h-11 min-w-11 p-2 shrink-0"
                aria-label="Actions"
              />
            }
          >
            <MoreVertical className="h-4 w-4" aria-hidden="true" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onViewDetails(user)}>
              <Shield className="mr-2 h-4 w-4" />
              {t("viewDetails")}
            </DropdownMenuItem>
            {user.is_active ? (
              <DropdownMenuItem onClick={() => onDeactivate(user)} className="text-destructive">
                <UserX className="mr-2 h-4 w-4" />
                {t("deactivate")}
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onClick={() => onReactivate(user)}>
                <UserCheck className="mr-2 h-4 w-4" />
                {t("reactivate")}
              </DropdownMenuItem>
            )}
            {user.role !== "expert" && (
              <DropdownMenuItem onClick={() => onPromote(user, "expert")}>
                <ShieldCheck className="mr-2 h-4 w-4" />
                {t("promoteToExpert")}
              </DropdownMenuItem>
            )}
            {user.role !== "admin" && (
              <DropdownMenuItem onClick={() => onPromote(user, "admin")}>
                <ShieldCheck className="mr-2 h-4 w-4" />
                {t("promoteToAdmin")}
              </DropdownMenuItem>
            )}
            {user.role !== "user" && (
              <DropdownMenuItem onClick={() => onPromote(user, "user")}>
                <ShieldOff className="mr-2 h-4 w-4" />
                {t("demoteToUser")}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </td>
    </tr>
  );
}
