"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Share2, Copy, Check, MessageCircle, Send, Facebook } from "lucide-react";

interface ShareButtonProps {
  url: string;
  title: string;
  description?: string;
  variant?: "icon" | "button";
  className?: string;
}

export function ShareButton({
  url,
  title,
  description,
  variant = "icon",
  className = "",
}: ShareButtonProps) {
  const t = useTranslations("Share");
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const fullUrl = typeof window !== "undefined" ? `${window.location.origin}${url}` : url;
  const shareText = description ? `${title} — ${description}` : title;

  const handleShare = async (e: React.MouseEvent) => {
    e.stopPropagation();

    // Use native share API if available (mobile)
    if (navigator.share) {
      try {
        await navigator.share({ title, text: shareText, url: fullUrl });
        return;
      } catch {
        // User cancelled or not supported — fall through to menu
      }
    }
    setOpen(!open);
  };

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => {
      setCopied(false);
      setOpen(false);
    }, 1500);
  };

  const handleWhatsApp = (e: React.MouseEvent) => {
    e.stopPropagation();
    const text = encodeURIComponent(`${shareText}\n${fullUrl}`);
    window.open(`https://wa.me/?text=${text}`, "_blank");
    setOpen(false);
  };

  const handleTelegram = (e: React.MouseEvent) => {
    e.stopPropagation();
    const text = encodeURIComponent(shareText);
    const link = encodeURIComponent(fullUrl);
    window.open(`https://t.me/share/url?url=${link}&text=${text}`, "_blank");
    setOpen(false);
  };

  const handleFacebook = (e: React.MouseEvent) => {
    e.stopPropagation();
    const link = encodeURIComponent(fullUrl);
    window.open(`https://www.facebook.com/sharer/sharer.php?u=${link}`, "_blank");
    setOpen(false);
  };

  return (
    <div className={`relative ${className}`} ref={menuRef}>
      <button
        type="button"
        onClick={handleShare}
        className={
          variant === "button"
            ? "inline-flex items-center gap-2 rounded-md border border-stone-300 px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 transition-colors min-h-[40px]"
            : "p-2 rounded-full hover:bg-stone-100 transition-colors text-stone-500 hover:text-stone-700"
        }
        aria-label={t("share")}
      >
        <Share2 className="h-4 w-4" />
        {variant === "button" && <span>{t("share")}</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] rounded-lg border border-stone-200 bg-white shadow-lg py-1 animate-in fade-in-0 zoom-in-95">
          <button
            type="button"
            onClick={handleWhatsApp}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-stone-700 hover:bg-stone-50 transition-colors"
          >
            <MessageCircle className="h-4 w-4 text-green-600" />
            WhatsApp
          </button>
          <button
            type="button"
            onClick={handleTelegram}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-stone-700 hover:bg-stone-50 transition-colors"
          >
            <Send className="h-4 w-4 text-blue-500" />
            Telegram
          </button>
          <button
            type="button"
            onClick={handleFacebook}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-stone-700 hover:bg-stone-50 transition-colors"
          >
            <Facebook className="h-4 w-4 text-blue-600" />
            Facebook
          </button>
          <div className="border-t border-stone-100 my-1" />
          <button
            type="button"
            onClick={handleCopy}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-stone-700 hover:bg-stone-50 transition-colors"
          >
            {copied ? (
              <>
                <Check className="h-4 w-4 text-green-600" />
                {t("copied")}
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" />
                {t("copyLink")}
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
