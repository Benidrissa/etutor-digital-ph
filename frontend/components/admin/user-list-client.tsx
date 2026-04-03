"use client";

import { useState, useCallback, useRef } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";
import { authClient } from "@/lib/auth";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type UserRole = "user" | "expert" | "admin";

interface UserProfile {
  id: string;
  email: string;
  name: string;
  preferred_language: string;
  country: string | null;
  professional_role: string | null;
  current_level: number;
  streak_days: number;
  avatar_url: string | null;
  last_active: string;
  created_at: string;
  role: UserRole;
}

interface AdminUsersResponse {
  items: UserProfile[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

const ROLE_BADGE_VARIANT: Record<UserRole, "default" | "secondary" | "outline"> = {
  admin: "default",
  expert: "secondary",
  user: "outline",
};

const ECOWAS_COUNTRIES = [
  "benin",
  "burkina-faso",
  "cabo-verde",
  "cote-divoire",
  "gambia",
  "ghana",
  "guinea",
  "guinea-bissau",
  "liberia",
  "mali",
  "niger",
  "nigeria",
  "senegal",
  "sierra-leone",
  "togo",
];

const ALL_ROLES: UserRole[] = ["user", "expert", "admin"];

async function fetchAdminUsers(params: {
  search?: string;
  role?: string;
  country?: string;
  level?: string;
  page: number;
}): Promise<AdminUsersResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.role && params.role !== "all") query.set("role", params.role);
  if (params.country && params.country !== "all") query.set("country", params.country);
  if (params.level && params.level !== "all") query.set("level", params.level);
  query.set("page", String(params.page));
  query.set("limit", "20");

  return authClient.authenticatedFetch<AdminUsersResponse>(
    `/api/v1/admin/users?${query.toString()}`
  );
}

async function patchUserRole(userId: string, role: UserRole): Promise<UserProfile> {
  return authClient.authenticatedFetch<UserProfile>(`/api/v1/admin/users/${userId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

function formatLastActive(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function UserListClient() {
  const t = useTranslations("Admin.users");
  const tRoles = useTranslations("Roles");
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [countryFilter, setCountryFilter] = useState("all");
  const [levelFilter, setLevelFilter] = useState("all");
  const [page, setPage] = useState(1);

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setSearch(value);
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        setDebouncedSearch(value);
        setPage(1);
      }, 400);
    },
    []
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-users", debouncedSearch, roleFilter, countryFilter, levelFilter, page],
    queryFn: () =>
      fetchAdminUsers({
        search: debouncedSearch || undefined,
        role: roleFilter,
        country: countryFilter,
        level: levelFilter,
        page,
      }),
    staleTime: 30_000,
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      patchUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const totalPages = data ? Math.ceil(data.total / data.limit) : 1;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:flex-wrap">
        <div className="relative flex-1 min-w-0">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            className="pl-8 h-9"
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={handleSearch}
            aria-label={t("searchPlaceholder")}
          />
        </div>

        <Select
          value={roleFilter}
          onValueChange={(v) => {
            setRoleFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-full sm:w-36 h-9" aria-label={t("filterRole")}>
            <SelectValue placeholder={t("filterRole")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allRoles")}</SelectItem>
            <SelectItem value="user">{tRoles("user")}</SelectItem>
            <SelectItem value="expert">{tRoles("expert")}</SelectItem>
            <SelectItem value="admin">{tRoles("admin")}</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={countryFilter}
          onValueChange={(v) => {
            setCountryFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-full sm:w-40 h-9" aria-label={t("filterCountry")}>
            <SelectValue placeholder={t("filterCountry")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allCountries")}</SelectItem>
            {ECOWAS_COUNTRIES.map((c) => (
              <SelectItem key={c} value={c}>
                {c.replace(/-/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={levelFilter}
          onValueChange={(v) => {
            setLevelFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-full sm:w-32 h-9" aria-label={t("filterLevel")}>
            <SelectValue placeholder={t("filterLevel")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allLevels")}</SelectItem>
            {[1, 2, 3, 4].map((l) => (
              <SelectItem key={l} value={String(l)}>
                {t("level", { level: l })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {data && (
        <p className="text-sm text-muted-foreground">
          {t("totalUsers", { count: data.total })}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b bg-muted/50 text-muted-foreground">
              <th className="px-4 py-2.5 text-left font-medium">{t("columnName")}</th>
              <th className="px-4 py-2.5 text-left font-medium">{t("columnEmail")}</th>
              <th className="px-4 py-2.5 text-left font-medium">{t("columnRole")}</th>
              <th className="px-4 py-2.5 text-left font-medium">{t("columnCountry")}</th>
              <th className="px-4 py-2.5 text-left font-medium">{t("columnLevel")}</th>
              <th className="px-4 py-2.5 text-left font-medium">{t("columnLastActive")}</th>
              <th className="px-4 py-2.5 text-left font-medium sr-only">{t("columnActions")}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b animate-pulse">
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 rounded bg-muted" />
                    </td>
                  ))}
                </tr>
              ))}
            {!isLoading && error && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                  {t("noUsers")}
                </td>
              </tr>
            )}
            {!isLoading && data && data.items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center">
                  <p className="font-medium">{t("noUsers")}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{t("noUsersDescription")}</p>
                </td>
              </tr>
            )}
            {!isLoading &&
              data &&
              data.items.map((user) => (
                <tr
                  key={user.id}
                  className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                >
                  <td className="px-4 py-3 font-medium">{user.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">{user.email}</td>
                  <td className="px-4 py-3">
                    <Badge variant={ROLE_BADGE_VARIANT[user.role]}>{tRoles(user.role)}</Badge>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground capitalize">
                    {user.country ? user.country.replace(/-/g, " ") : "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {t("level", { level: user.current_level })}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatLastActive(user.last_active)}
                  </td>
                  <td className="px-4 py-3">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0"
                          aria-label={t("changeRole")}
                        >
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {ALL_ROLES.filter((r) => r !== user.role).map((r, i, arr) => (
                          <div key={r}>
                            <DropdownMenuItem
                              onSelect={() => roleMutation.mutate({ userId: user.id, role: r })}
                              disabled={roleMutation.isPending}
                            >
                              {t("setRole", { role: tRoles(r) })}
                            </DropdownMenuItem>
                            {i < arr.length - 1 && <DropdownMenuSeparator />}
                          </div>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {data && totalPages > 1 && (
        <div className="flex items-center justify-between gap-2 pt-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            aria-label={t("previous")}
          >
            <ChevronLeft className="size-4 mr-1" />
            {t("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageOf", { page, total: totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => p + 1)}
            disabled={!data.has_next}
            aria-label={t("next")}
          >
            {t("next")}
            <ChevronRight className="size-4 ml-1" />
          </Button>
        </div>
      )}
    </div>
  );
}
