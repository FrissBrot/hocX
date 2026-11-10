"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ActionIcon } from "@/components/ui/action-icons";

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5 6.2 11.5 13 4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function CopyField({ label, value }: { label: string; value: string }) {
  const t = useTranslations("common.copyField");
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard-Zugriff kann in manchen Browsern/Kontexten fehlschlagen - kein Beinbruch,
      // der Wert steht trotzdem sichtbar da und kann markiert werden.
    }
  }

  return (
    <div className="wizard-dns-row">
      <button type="button" className="wizard-dns-value wizard-dns-value-button" onClick={copy} aria-label={t("copyWithLabel", { label })} title={t("copy")}>
        {value}
      </button>
      <button type="button" className={`wizard-copy-button${copied ? " is-copied" : ""}`} onClick={copy} aria-label={t("copyWithLabel", { label })} title={t("copy")}>
        {copied ? <CheckIcon /> : <ActionIcon name="copy" />}
      </button>
    </div>
  );
}
