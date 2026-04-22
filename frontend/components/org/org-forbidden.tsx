"use client";

import Link from "next/link";
import { useLocale } from "next-intl";
import { ShieldOff } from "lucide-react";

const MESSAGES = {
  fr: {
    heading: "403 — Accès refusé",
    body: "Vous n'avez pas les droits nécessaires pour gérer les banques de questions de cette organisation.",
    ctaLearner: "Retour aux tests disponibles",
  },
  en: {
    heading: "403 — Forbidden",
    body: "You don't have permission to manage this organization's question banks.",
    ctaLearner: "Back to available tests",
  },
} as const;

export function OrgQBankForbidden() {
  const locale = useLocale();
  const m = locale === "en" ? MESSAGES.en : MESSAGES.fr;
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 rounded-lg border bg-white p-10 text-center">
      <ShieldOff className="h-10 w-10 text-red-500" aria-hidden />
      <h1 className="text-xl font-semibold">{m.heading}</h1>
      <p className="text-sm text-muted-foreground">{m.body}</p>
      <Link
        href={`/${locale}/qbank`}
        className="inline-flex items-center rounded-md border px-4 py-2 text-sm font-medium hover:bg-gray-50"
      >
        {m.ctaLearner}
      </Link>
    </div>
  );
}
