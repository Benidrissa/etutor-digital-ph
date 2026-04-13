"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { createOrganization } from "@/lib/api";
import { Building2, ArrowLeft } from "lucide-react";
import Link from "next/link";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export default function CreateOrganizationPage() {
  const t = useTranslations("Organization");
  const locale = useLocale();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManual, setSlugManual] = useState(false);
  const [description, setDescription] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleNameChange = (val: string) => {
    setName(val);
    if (!slugManual) {
      setSlug(slugify(val));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const org = await createOrganization({
        name: name.trim(),
        slug: slug || undefined,
        description: description || undefined,
        contact_email: contactEmail || undefined,
      });
      router.push(`/${locale}/org/${org.slug}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div>
        <Link
          href={`/${locale}/organizations`}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("title")}
        </Link>
        <h1 className="text-2xl font-bold flex items-center gap-3">
          <Building2 className="h-6 w-6 text-green-600" />
          {t("createOrg")}
        </h1>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border bg-white p-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("orgName")} *
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            required
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder="My Organization"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("orgSlug")}
          </label>
          <input
            type="text"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setSlugManual(true);
            }}
            className="w-full rounded-md border px-3 py-2 text-sm font-mono"
            placeholder="my-organization"
          />
          <p className="text-xs text-gray-400 mt-1">
            URL: /org/{slug || "..."}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("orgDescription")}
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("contactEmail")}
          </label>
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder="contact@organization.com"
          />
        </div>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="w-full rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {submitting ? "..." : t("createOrg")}
        </button>
      </form>
    </div>
  );
}
