"use client";

import { useState } from "react";

function CopyIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M3.5 10.5h-1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5 6.2 11.5 13 4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function CopyField({ label, value }: { label: string; value: string }) {
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
      <button type="button" className="wizard-dns-value wizard-dns-value-button" onClick={copy} aria-label={`${label} kopieren`} title="Kopieren">
        {value}
      </button>
      <button type="button" className={`wizard-copy-button${copied ? " is-copied" : ""}`} onClick={copy} aria-label={`${label} kopieren`} title="Kopieren">
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </div>
  );
}
