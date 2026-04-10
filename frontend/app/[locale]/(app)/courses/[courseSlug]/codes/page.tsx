"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { Link } from "@/i18n/routing";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft,
  Copy,
  Check,
  Download,
  ChevronDown,
  ChevronRight,
  QrCode,
} from "lucide-react";
import {
  getActivationCodes,
  generateActivationCodes,
  getCodeRedemptions,
  getCodeQR,
  manualActivate,
  apiFetch,
  type ActivationCodeResponse,
  type CodeRedemptionResponse,
} from "@/lib/api";

function getCodeStatus(code: ActivationCodeResponse): "active" | "exhausted" | "inactive" {
  if (!code.is_active) return "inactive";
  if (code.max_uses != null && code.times_used >= code.max_uses) return "exhausted";
  return "active";
}

interface CourseBasic {
  id: string;
  title_fr: string;
  title_en: string;
  created_by?: string;
}

function getStoredUserRole(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const user = localStorage.getItem("user");
    if (!user) return null;
    const parsed = JSON.parse(user) as { role?: string };
    return parsed.role ?? null;
  } catch {
    return null;
  }
}

function StatusBadge({ status, t }: { status: "active" | "exhausted" | "inactive"; t: (key: string) => string }) {
  const classes: Record<string, string> = {
    active: "bg-green-100 text-green-700 border-green-200",
    exhausted: "bg-stone-100 text-stone-500 border-stone-200",
    inactive: "bg-red-100 text-red-700 border-red-200",
  };
  return (
    <Badge variant="outline" className={`text-xs ${classes[status] ?? ""}`}>
      {t(`status.${status}`)}
    </Badge>
  );
}

function MethodBadge({ method, t }: { method: CodeRedemptionResponse["method"]; t: (key: string) => string }) {
  const classes: Record<string, string> = {
    code: "bg-blue-100 text-blue-700 border-blue-200",
    qr: "bg-purple-100 text-purple-700 border-purple-200",
    manual: "bg-amber-100 text-amber-700 border-amber-200",
  };
  return (
    <Badge variant="outline" className={`text-xs ${classes[method] ?? ""}`}>
      {t(`method.${method}`)}
    </Badge>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={label}
      className="inline-flex items-center justify-center h-8 w-8 rounded-md hover:bg-stone-100 transition-colors text-stone-500"
    >
      {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

export default function ExpertCodesPage() {
  const t = useTranslations("expertCodes");
  const locale = useLocale() as "fr" | "en";
  const params = useParams();
  const router = useRouter();

  const courseSlug = params.courseSlug as string;

  const [course, setCourse] = useState<CourseBasic | null>(null);
  const [codes, setCodes] = useState<ActivationCodeResponse[]>([]);
  const [loadingCodes, setLoadingCodes] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [generateCount, setGenerateCount] = useState(1);
  const [generateMaxUses, setGenerateMaxUses] = useState<string>("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [newCodes, setNewCodes] = useState<ActivationCodeResponse[]>([]);

  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [redemptions, setRedemptions] = useState<Record<string, CodeRedemptionResponse[]>>({});
  const [loadingRedemptions, setLoadingRedemptions] = useState<Record<string, boolean>>({});

  const [manualCodeId, setManualCodeId] = useState<string>("");
  const [manualEmail, setManualEmail] = useState("");
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);
  const [activateSuccess, setActivateSuccess] = useState(false);

  const [role] = useState(() => getStoredUserRole());

  useEffect(() => {
    if (role && !["expert", "admin"].includes(role)) {
      router.replace("/dashboard");
    }
  }, [role, router]);

  useEffect(() => {
    apiFetch<CourseBasic>(`/api/v1/courses/${courseSlug}`)
      .then(setCourse)
      .catch(() => {});
  }, [courseSlug]);

  const loadCodes = useCallback(async () => {
    if (!course) return;
    setLoadingCodes(true);
    setLoadError(null);
    try {
      const data = await getActivationCodes(course.id);
      setCodes(data);
    } catch {
      setLoadError(t("errorLoading"));
    } finally {
      setLoadingCodes(false);
    }
  }, [course, t]);

  useEffect(() => {
    if (course) {
      loadCodes();
    }
  }, [course, loadCodes]);

  const handleGenerate = async () => {
    if (!course) return;
    setGenerating(true);
    setGenerateError(null);
    setNewCodes([]);
    try {
      const maxUses = generateMaxUses.trim() !== "" ? parseInt(generateMaxUses, 10) : undefined;
      const result = await generateActivationCodes(course.id, generateCount, maxUses);
      setNewCodes(result);
      await loadCodes();
    } catch {
      setGenerateError(t("errorGenerating"));
    } finally {
      setGenerating(false);
    }
  };

  const handleExpandCode = async (codeId: string) => {
    if (expandedCode === codeId) {
      setExpandedCode(null);
      return;
    }
    setExpandedCode(codeId);
    if (!redemptions[codeId] && !loadingRedemptions[codeId] && course) {
      setLoadingRedemptions((prev) => ({ ...prev, [codeId]: true }));
      try {
        const data = await getCodeRedemptions(course.id, codeId);
        setRedemptions((prev) => ({ ...prev, [codeId]: data }));
      } catch {
        setRedemptions((prev) => ({ ...prev, [codeId]: [] }));
      } finally {
        setLoadingRedemptions((prev) => ({ ...prev, [codeId]: false }));
      }
    }
  };

  const handleDownloadQR = async (codeId: string) => {
    if (!course) return;
    try {
      const blob = await getCodeQR(course.id, codeId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `activation-qr-${codeId}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    }
  };

  const handleManualActivate = async () => {
    if (!course || !manualCodeId || !manualEmail.trim()) return;
    setActivating(true);
    setActivateError(null);
    setActivateSuccess(false);
    try {
      await manualActivate(course.id, manualCodeId, manualEmail.trim());
      setActivateSuccess(true);
      setManualEmail("");
      await loadCodes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("not found") || msg.includes("404")) {
        setActivateError(t("learnerNotFound"));
      } else if (msg.includes("already") || msg.includes("409")) {
        setActivateError(t("alreadyEnrolled"));
      } else {
        setActivateError(t("errorActivating"));
      }
    } finally {
      setActivating(false);
    }
  };

  const courseTitle = course ? (locale === "fr" ? course.title_fr : course.title_en) : "";

  const formatDate = (dateStr: string) =>
    new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date(dateStr));

  return (
    <div className="container mx-auto max-w-3xl px-4 py-6 space-y-6 pb-24 md:pb-8">
      <Link
        href={`/courses/${courseSlug}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("backToCourse")}
        {courseTitle ? ` — ${courseTitle}` : ""}
      </Link>

      <h1 className="text-2xl font-bold text-stone-900">{t("title")}</h1>

      {/* Section A: Generate Codes */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("generate")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="gen-count">{t("count")}</Label>
              <Input
                id="gen-count"
                type="number"
                min={1}
                max={50}
                value={generateCount}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!isNaN(v)) setGenerateCount(Math.min(50, Math.max(1, v)));
                }}
                className="min-h-11"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gen-max-uses">{t("maxUses")}</Label>
              <Input
                id="gen-max-uses"
                type="number"
                min={1}
                placeholder={t("unlimited")}
                value={generateMaxUses}
                onChange={(e) => setGenerateMaxUses(e.target.value)}
                className="min-h-11"
              />
            </div>
          </div>

          {generateError && (
            <p className="text-sm text-destructive" role="alert">{generateError}</p>
          )}

          <Button
            onClick={handleGenerate}
            disabled={generating || !course}
            className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
          >
            {generating ? t("generating") : t("generate")}
          </Button>

          {newCodes.length > 0 && (
            <div className="space-y-2 pt-2">
              {newCodes.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-2 rounded-md border bg-stone-50 px-3 py-2"
                >
                  <span className="flex-1 font-mono text-sm text-stone-800 break-all">{c.code}</span>
                  <CopyButton value={c.code} label={t("copyCode")} />
                  <button
                    type="button"
                    onClick={() => handleDownloadQR(c.id)}
                    aria-label={t("downloadQr")}
                    className="inline-flex items-center justify-center h-8 w-8 rounded-md hover:bg-stone-200 transition-colors text-stone-500"
                  >
                    <QrCode className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Section B: Codes Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {loadingCodes ? (
            <div className="flex items-center justify-center py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-teal-600 border-t-transparent" />
            </div>
          ) : loadError ? (
            <p className="text-sm text-destructive px-6 pb-4" role="alert">{loadError}</p>
          ) : codes.length === 0 ? (
            <div className="px-6 pb-6 text-center text-sm text-stone-500">
              <p className="font-medium">{t("noCodes")}</p>
              <p className="mt-1">{t("noCodesDescription")}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-stone-50">
                    <th className="px-4 py-3 text-left font-medium text-stone-600">{t("codeColumn")}</th>
                    <th className="px-4 py-3 text-left font-medium text-stone-600">{t("usesColumn")}</th>
                    <th className="px-4 py-3 text-left font-medium text-stone-600 hidden sm:table-cell">{t("revenueColumn")}</th>
                    <th className="px-4 py-3 text-left font-medium text-stone-600">{t("statusColumn")}</th>
                    <th className="px-4 py-3 text-left font-medium text-stone-600 hidden md:table-cell">{t("createdColumn")}</th>
                    <th className="px-4 py-3 text-left font-medium text-stone-600">{t("actionsColumn")}</th>
                  </tr>
                </thead>
                <tbody>
                  {codes.map((code) => (
                    <>
                      <tr
                        key={code.id}
                        className="border-b hover:bg-stone-50 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <span className="font-mono text-xs text-stone-700 truncate max-w-[120px]">
                              {code.code}
                            </span>
                            <CopyButton value={code.code} label={t("copyCode")} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-stone-700">
                          {code.times_used}/{code.max_uses ?? "∞"}
                        </td>
                        <td className="px-4 py-3 text-stone-700 hidden sm:table-cell">
                          {code.revenue_credits != null ? t("credits", { count: code.revenue_credits }) : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={getCodeStatus(code)} t={t} />
                        </td>
                        <td className="px-4 py-3 text-stone-500 hidden md:table-cell">
                          {formatDate(code.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => handleDownloadQR(code.id)}
                              aria-label={t("downloadQr")}
                              className="inline-flex items-center justify-center h-8 w-8 rounded-md hover:bg-stone-100 transition-colors text-stone-500"
                            >
                              <Download className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => handleExpandCode(code.id)}
                              aria-label={
                                expandedCode === code.id
                                  ? t("collapseRedemptions")
                                  : t("expandRedemptions")
                              }
                              className="inline-flex items-center justify-center h-8 w-8 rounded-md hover:bg-stone-100 transition-colors text-stone-500"
                            >
                              {expandedCode === code.id ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {expandedCode === code.id && (
                        <tr key={`${code.id}-redemptions`} className="bg-stone-50">
                          <td colSpan={6} className="px-6 py-3">
                            <p className="text-xs font-semibold text-stone-500 uppercase mb-2">
                              {t("redemptions")}
                            </p>
                            {loadingRedemptions[code.id] ? (
                              <div className="flex items-center gap-2 py-2 text-sm text-stone-500">
                                <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
                              </div>
                            ) : !redemptions[code.id] || redemptions[code.id].length === 0 ? (
                              <p className="text-sm text-stone-500">{t("noRedemptions")}</p>
                            ) : (
                              <div className="overflow-x-auto">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="border-b">
                                      <th className="pb-2 text-left font-medium text-stone-500">{t("learner")}</th>
                                      <th className="pb-2 text-left font-medium text-stone-500">{t("date")}</th>
                                      <th className="pb-2 text-left font-medium text-stone-500">{t("methodColumn")}</th>
                                      <th className="pb-2 text-left font-medium text-stone-500">{t("revenueColumn")}</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {redemptions[code.id].map((r) => (
                                      <tr key={r.id} className="border-b last:border-0">
                                        <td className="py-2 pr-4">
                                          <span className="font-medium text-stone-800">{r.learner_name}</span>
                                          <span className="text-stone-500 ml-1">({r.learner_email})</span>
                                        </td>
                                        <td className="py-2 pr-4 text-stone-600">{formatDate(r.redeemed_at)}</td>
                                        <td className="py-2 pr-4">
                                          <MethodBadge method={r.method} t={t} />
                                        </td>
                                        <td className="py-2 text-stone-600">
                                          {t("credits", { count: r.revenue_credits })}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Section C: Manual Activation */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("manualActivate")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="manual-code">{t("codeColumn")}</Label>
            <Select value={manualCodeId} onValueChange={(v) => setManualCodeId(v ?? "")}>
              <SelectTrigger id="manual-code" className="min-h-11">
                <SelectValue placeholder={t("selectCode")} />
              </SelectTrigger>
              <SelectContent>
                {codes
                  .filter((c) => getCodeStatus(c) === "active")
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      <span className="font-mono text-xs">{c.code}</span>
                      <span className="ml-2 text-stone-500 text-xs">
                        ({c.times_used}/{c.max_uses ?? "∞"})
                      </span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="manual-email">{t("learnerEmail")}</Label>
            <Input
              id="manual-email"
              type="email"
              value={manualEmail}
              onChange={(e) => {
                setManualEmail(e.target.value);
                setActivateError(null);
                setActivateSuccess(false);
              }}
              placeholder="learner@example.com"
              className="min-h-11"
            />
          </div>

          {activateError && (
            <p className="text-sm text-destructive" role="alert">{activateError}</p>
          )}
          {activateSuccess && (
            <p className="text-sm text-green-600" role="status">{t("activateSuccess")}</p>
          )}

          <Button
            onClick={handleManualActivate}
            disabled={activating || !manualCodeId || !manualEmail.trim() || !course}
            className="w-full min-h-11 bg-teal-600 hover:bg-teal-700"
          >
            {activating ? t("activating") : t("activate")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
