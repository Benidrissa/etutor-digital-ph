"use client";

import { useState, useCallback, useTransition } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Download, MoreVertical, UserCheck, UserX, ShieldCheck, ShieldOff, Shield, ChevronLeft, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
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

const PAGE_SIZE = 50;

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
}) {
  const query = buildFilterQuery(params);
  query.set("offset", String(params.offset));
  query.set("limit", String(PAGE_SIZE));

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
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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

  const { data: users, isLoading, error } = useAdminUsers({ ...filterParams, offset });
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

        <select
          className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={country}
          onChange={(e) => { setCountry(e.target.value); setOffset(0); }}
          aria-label={t("filterCountry")}
        >
          <option value="">{t("allCountries")}</option>
          {["benin", "burkina-faso", "cote-divoire", "ghana", "mali", "niger", "nigeria", "senegal", "togo"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

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
          <div className="flex flex-col gap-2">
            {users.map((user) => (
              <UserCard
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
          </div>
          {countData && countData.count > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 pt-2">
              <Button
                variant="outline"
                size="sm"
                className="min-h-11 min-w-11 gap-2"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                aria-label={t("prevPage")}
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{t("prevPage")}</span>
              </Button>
              <span className="text-sm text-muted-foreground">
                {t("pageIndicator", {
                  page: Math.floor(offset / PAGE_SIZE) + 1,
                  total: Math.ceil(countData.count / PAGE_SIZE),
                })}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="min-h-11 min-w-11 gap-2"
                disabled={offset + PAGE_SIZE >= countData.count}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                aria-label={t("nextPage")}
              >
                <span className="hidden sm:inline">{t("nextPage")}</span>
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          )}
        </div>
      )}

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
    </div>
  );
}

function UserCard({
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
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <button
          className="flex flex-col gap-1 text-left min-w-0 flex-1"
          onClick={() => onViewDetails(user)}
          aria-label={t("viewDetails")}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{user.name}</span>
            <Badge variant={roleVariant}>{tRoles(user.role)}</Badge>
            {!user.is_active && (
              <Badge variant="destructive">{t("inactive")}</Badge>
            )}
          </div>
          {user.email && (
            <span className="text-xs text-muted-foreground truncate">{user.email}</span>
          )}
          {user.phone_number && (
            <span className="text-xs text-muted-foreground truncate">{user.phone_number}</span>
          )}
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            {user.country && (
              <span className="text-xs text-muted-foreground">{user.country}</span>
            )}
            <span className="text-xs text-muted-foreground">{t("level", { level: user.current_level })}</span>
          </div>
        </button>

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
      </div>
    </Card>
  );
}
