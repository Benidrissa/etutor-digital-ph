"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { useOrg } from "./org-context";

export function OrgGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const locale = useLocale();
  const { org, loading } = useOrg();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!org) {
      router.replace(`/${locale}/dashboard`);
      return;
    }
    setReady(true);
  }, [loading, org, router, locale]);

  if (!ready) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600" />
      </div>
    );
  }

  return <>{children}</>;
}
