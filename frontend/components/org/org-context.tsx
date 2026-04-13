"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { OrgResponse } from "@/lib/api";
import { fetchOrganization, fetchMyOrganizations } from "@/lib/api";

interface OrgContextValue {
  org: OrgResponse | null;
  role: string | null;
  loading: boolean;
  orgId: string | null;
}

const OrgContext = createContext<OrgContextValue>({
  org: null,
  role: null,
  loading: true,
  orgId: null,
});

export function useOrg() {
  return useContext(OrgContext);
}

export function OrgProvider({
  orgSlug,
  children,
}: {
  orgSlug: string;
  children: React.ReactNode;
}) {
  const [org, setOrg] = useState<OrgResponse | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const memberships = await fetchMyOrganizations();
        const match = memberships.find((m) => m.organization.slug === orgSlug);
        if (match) {
          setOrg(match.organization);
          setRole(match.role);
        } else {
          // Try fetching directly (admin bypass)
          try {
            const orgData = await fetchOrganization(orgSlug);
            setOrg(orgData);
            setRole("admin");
          } catch {
            setOrg(null);
          }
        }
      } catch {
        setOrg(null);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [orgSlug]);

  return (
    <OrgContext.Provider value={{ org, role, loading, orgId: org?.id ?? null }}>
      {children}
    </OrgContext.Provider>
  );
}
