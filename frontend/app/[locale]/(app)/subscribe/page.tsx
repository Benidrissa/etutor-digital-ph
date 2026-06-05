"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  apiFetch,
  fetchEnabledPaymentProviders,
  initializePayment,
  type PaymentProvider,
} from "@/lib/api";
import {
  Phone,
  CheckCircle,
  Clock,
  Sparkles,
  Gift,
  ArrowRight,
  Smartphone,
  CreditCard,
  Loader2,
} from "lucide-react";

interface SubscriptionStatus {
  has_subscription: boolean;
  subscription_status?: string;
  days_remaining?: number;
  daily_message_limit?: number;
  expires_at?: string;
  free_tier?: { daily_messages: number; first_lesson_free: boolean };
}

const PROVIDER_META: Record<
  PaymentProvider,
  { labelKey: string; icon: typeof Smartphone; accent: string }
> = {
  orange_money: { labelKey: "methodOrangeMoney", icon: Smartphone, accent: "text-orange-600" },
  wave: { labelKey: "methodWave", icon: Smartphone, accent: "text-sky-600" },
  paystack: { labelKey: "methodCard", icon: CreditCard, accent: "text-emerald-600" },
};

export default function SubscribePage() {
  const t = useTranslations("Subscribe");
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [phone, setPhone] = useState("");
  const [currentPhone, setCurrentPhone] = useState<string | null>(null);
  const [phoneLoading, setPhoneLoading] = useState(false);
  const [phoneMessage, setPhoneMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState<PaymentProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<PaymentProvider | null>(null);
  const [payLoading, setPayLoading] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiFetch<SubscriptionStatus>("/api/v1/subscriptions/me");
      setStatus(data);
    } catch {
      // Ignore — user might not be authenticated yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    // Also try to get current phone from user profile
    apiFetch<{ phone_number?: string }>("/api/v1/users/me")
      .then((user) => {
        if (user.phone_number) {
          setCurrentPhone(user.phone_number);
          setPhone(user.phone_number);
        }
      })
      .catch(() => {});
    // Which payment methods has the admin enabled?
    fetchEnabledPaymentProviders()
      .then((list) => {
        setProviders(list);
        if (list.length > 0) setSelectedProvider(list[0]);
      })
      .catch(() => {});
  }, [fetchStatus]);

  // Handle the provider's return redirect (/subscribe?status=success&ref=…):
  // verify the reference then poll subscription status until it flips active.
  useEffect(() => {
    const returnStatus = searchParams.get("status");
    const ref = searchParams.get("ref");
    if (returnStatus !== "success" || !ref) return;

    let cancelled = false;
    setVerifying(true);
    (async () => {
      try {
        await apiFetch(`/api/v1/payments/verify/${ref}`).catch(() => {});
        for (let i = 0; i < 5 && !cancelled; i++) {
          await fetchStatus();
          await new Promise((r) => setTimeout(r, 2000));
        }
      } finally {
        if (!cancelled) setVerifying(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchParams, fetchStatus]);

  const handlePay = async () => {
    if (!selectedProvider) return;
    setPayLoading(true);
    setPayError(null);
    try {
      const { checkout_url } = await initializePayment(selectedProvider, "access");
      window.location.href = checkout_url;
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("paymentError");
      setPayError(msg);
      setPayLoading(false);
    }
  };

  const handlePhoneSave = async () => {
    setPhoneLoading(true);
    setPhoneMessage(null);
    try {
      await apiFetch("/api/v1/users/phone", {
        method: "POST",
        body: JSON.stringify({ phone_number: phone }),
      });
      setCurrentPhone(phone);
      setPhoneMessage({ type: "success", text: t("phoneSuccess") });
      fetchStatus();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error";
      setPhoneMessage({ type: "error", text: msg });
    } finally {
      setPhoneLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const isActive =
    status?.has_subscription && status.subscription_status === "active";
  const isAdmin = (status?.daily_message_limit ?? 0) >= 9999;

  return (
    <div className="container mx-auto max-w-2xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-stone-900">{t("title")}</h1>
        <p className="text-stone-600 mt-1">{t("subtitle")}</p>
      </div>

      {/* Verifying a returning payment */}
      {verifying && !isActive && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="flex items-center gap-3 pt-6">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <span className="text-sm text-stone-700">{t("verifyingPayment")}</span>
          </CardContent>
        </Card>
      )}

      {/* Current subscription status */}
      {isActive && !isAdmin && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3 mb-3">
              <CheckCircle className="h-6 w-6 text-green-600" />
              <span className="text-lg font-semibold text-green-800">
                {t("active")}
              </span>
            </div>
            <div className="space-y-1 text-sm text-green-700">
              <p>{t("daysRemaining", { days: status.days_remaining ?? 0 })}</p>
              <p>
                {t("messageLimit", { count: status.daily_message_limit ?? 0 })}
              </p>
              {status.expires_at && (
                <p>
                  {t("expiresAt", {
                    date: new Date(status.expires_at).toLocaleDateString(),
                  })}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Free tier info for non-subscribers */}
      {!isActive && !isAdmin && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("freeFeatures")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-stone-600">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-stone-400" />
              <span>{t("firstLessonFree")}</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-stone-400" />
              <span>{t("freeTier")}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Pricing card */}
      {!isAdmin && (
        <Card className="border-primary/30">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">{t("paidFeatures")}</CardTitle>
              <Badge variant="default" className="text-sm">
                {t("amount")}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span>{t("allCourses")}</span>
            </div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span>{t("tutorMessages")}</span>
            </div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span>{t("quizAccess")}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Payment method selector + checkout */}
      {!isAdmin && !isActive && providers.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              {t("selectMethod")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2">
              {providers.map((p) => {
                const meta = PROVIDER_META[p];
                const Icon = meta.icon;
                const selected = selectedProvider === p;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setSelectedProvider(p)}
                    aria-pressed={selected}
                    className={`flex min-h-[44px] items-center gap-3 rounded-lg border p-3 text-left transition ${
                      selected
                        ? "border-primary ring-1 ring-primary bg-primary/5"
                        : "border-stone-200 hover:border-stone-300"
                    }`}
                  >
                    <Icon className={`h-5 w-5 ${meta.accent}`} />
                    <span className="text-sm font-medium">{t(meta.labelKey)}</span>
                  </button>
                );
              })}
            </div>

            <Button
              onClick={handlePay}
              disabled={payLoading || !selectedProvider}
              className="w-full min-h-[44px]"
            >
              {payLoading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("redirecting")}
                </span>
              ) : (
                t("payNow")
              )}
            </Button>

            {payError && <p className="text-sm text-red-600">{payError}</p>}
          </CardContent>
        </Card>
      )}

      {/* No payment method configured */}
      {!isAdmin && !isActive && providers.length === 0 && (
        <Card>
          <CardContent className="flex items-start gap-3 pt-6">
            <Clock className="h-5 w-5 text-stone-400 mt-0.5" />
            <p className="text-sm text-stone-500">{t("noMethods")}</p>
          </CardContent>
        </Card>
      )}

      {/* Phone number input (optional — links phone for receipts/recovery) */}
      {!isAdmin && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Phone className="h-5 w-5" />
              {t("phoneLabel")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {currentPhone && (
              <p className="text-sm text-stone-500">
                {t("phoneCurrentLabel")}: <strong>{currentPhone}</strong>
              </p>
            )}
            <div className="flex gap-2">
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder={t("phonePlaceholder")}
                className="flex-1 rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <Button
                onClick={handlePhoneSave}
                disabled={phoneLoading || !phone.trim()}
                size="sm"
                className="min-h-[40px]"
              >
                {phoneLoading ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  t("phoneSave")
                )}
              </Button>
            </div>
            {phoneMessage && (
              <p
                className={`text-sm ${phoneMessage.type === "success" ? "text-green-600" : "text-red-600"}`}
              >
                {phoneMessage.text}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Top-up section */}
      {isActive && !isAdmin && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <ArrowRight className="h-5 w-5 text-primary mt-0.5" />
              <div>
                <p className="font-medium text-sm">{t("topUp")}</p>
                <p className="text-sm text-stone-500">{t("topUpDesc")}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Gift payment note */}
      {!isAdmin && (
        <Card className="bg-stone-50">
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <Gift className="h-5 w-5 text-stone-400 mt-0.5" />
              <p className="text-sm text-stone-500">{t("giftNote")}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
