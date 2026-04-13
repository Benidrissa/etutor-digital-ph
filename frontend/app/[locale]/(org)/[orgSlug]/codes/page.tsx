"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useOrg } from "@/components/org/org-context";
import {
  fetchOrgCodes,
  fetchOrgCurricula,
  generateOrgCodes,
  revokeOrgCode,
} from "@/lib/api";
import type { OrgCodeResponse, OrgCurriculumResponse } from "@/lib/api";
import { QrCode, Plus, XCircle, Copy, Check } from "lucide-react";

export default function OrgCodesPage() {
  const t = useTranslations("Organization");
  const { orgId } = useOrg();
  const [codes, setCodes] = useState<OrgCodeResponse[]>([]);
  const [curricula, setCurricula] = useState<OrgCurriculumResponse[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [formCurriculumId, setFormCurriculumId] = useState("");
  const [formCount, setFormCount] = useState(1);
  const [formMaxUses, setFormMaxUses] = useState<number | undefined>();
  const [generating, setGenerating] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  useEffect(() => {
    if (!orgId) return;
    fetchOrgCodes(orgId).then(setCodes).catch(() => {});
    fetchOrgCurricula(orgId).then(setCurricula).catch(() => {});
  }, [orgId]);

  const handleGenerate = async () => {
    if (!orgId) return;
    setGenerating(true);
    try {
      const newCodes = await generateOrgCodes(orgId, {
        curriculum_id: formCurriculumId || undefined,
        count: formCount,
        max_uses: formMaxUses,
      });
      setCodes((prev) => [...newCodes, ...prev]);
      setShowForm(false);
      setFormCurriculumId("");
      setFormCount(1);
      setFormMaxUses(undefined);
    } catch (err) {
      console.error(err);
    } finally {
      setGenerating(false);
    }
  };

  const handleRevoke = async (codeId: string) => {
    if (!orgId) return;
    try {
      await revokeOrgCode(orgId, codeId);
      setCodes((prev) =>
        prev.map((c) =>
          c.id === codeId ? { ...c, is_active: false } : c
        )
      );
    } catch (err) {
      console.error(err);
    }
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t("codes")}</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
        >
          <Plus className="h-4 w-4" />
          {t("generateCodes")}
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border bg-white p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("selectCurriculum")}
            </label>
            <select
              value={formCurriculumId}
              onChange={(e) => setFormCurriculumId(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
            >
              <option value="">-- {t("selectCurriculum")} --</option>
              {curricula.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title_en} / {c.title_fr}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t("codeCount")}
              </label>
              <input
                type="number"
                min={1}
                max={500}
                value={formCount}
                onChange={(e) => setFormCount(Number(e.target.value))}
                className="w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t("maxUses")}
              </label>
              <input
                type="number"
                min={1}
                value={formMaxUses ?? ""}
                onChange={(e) =>
                  setFormMaxUses(e.target.value ? Number(e.target.value) : undefined)
                }
                placeholder="Unlimited"
                className="w-full rounded-md border px-3 py-2 text-sm"
              />
            </div>
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {generating ? "..." : t("generateCodes")}
          </button>
        </div>
      )}

      <div className="rounded-lg border bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Code</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600 hidden md:table-cell">
                Curriculum
              </th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">Uses</th>
              <th className="px-4 py-3 text-center font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {codes.map((code) => {
              const curriculum = curricula.find((c) => c.id === code.curriculum_id);
              return (
                <tr key={code.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <QrCode className="h-4 w-4 text-gray-400" />
                      <span className="font-mono text-xs">{code.code}</span>
                      <button
                        onClick={() => copyCode(code.code)}
                        className="text-gray-400 hover:text-gray-600"
                      >
                        {copiedCode === code.code ? (
                          <Check className="h-3.5 w-3.5 text-green-500" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell text-gray-600">
                    {curriculum?.title_en || "-"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {code.times_used}
                    {code.max_uses ? `/${code.max_uses}` : ""}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        code.is_active
                          ? "bg-green-100 text-green-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {code.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {code.is_active && code.times_used === 0 && (
                      <button
                        onClick={() => handleRevoke(code.id)}
                        className="text-red-500 hover:text-red-700"
                        title={t("revoke")}
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {codes.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  No codes generated yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
