"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

// Sehr dezente Kennzeichnung, woher ein angezeigtes Bilddatum stammt: nichts bei echtem
// Aufnahmedatum, ein kleines "≈"-Kalendersymbol bei geschätztem Datum, ein kleines Info-Symbol,
// wenn mangels Aufnahmedatum das Uploaddatum verwendet wird. Ein Button statt reinem title,
// damit der Hinweis auch per Tastatur und auf Touch-Geräten (Tippen) erreichbar ist.
export type DateMarkerKind = "estimated" | "upload";

function EstimatedIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="2" y="3" width="12" height="11" rx="2" />
      <path d="M2 6.5h12M5 1.8v2.4M11 1.8v2.4" strokeLinecap="round" />
      <path d="M5.2 9.6c.8-.8 1.6-.8 2.4 0s1.6.8 2.4 0" strokeLinecap="round" />
    </svg>
  );
}

function InfoIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.2v3.8" strokeLinecap="round" />
      <circle cx="8" cy="4.9" r=".2" fill="currentColor" />
    </svg>
  );
}

export function PhotoDateMarker({ kind, count, total }: { kind: DateMarkerKind; count?: number; total?: number }) {
  const t = useTranslations("photos.dateMarker");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const partial = count !== undefined && total !== undefined && count < total;
  const base = kind === "estimated" ? t("estimated") : t("upload");
  const label = partial ? t("partial", { label: base, count: count!, total: total! }) : base;

  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event instanceof MouseEvent && ref.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", close);
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("mousedown", close);
    };
  }, [open]);

  return (
    <span ref={ref} className="photo-date-marker">
      <button
        type="button"
        className={`photo-date-marker-button photo-date-marker-${kind}`}
        aria-label={label}
        aria-expanded={open}
        title={label}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        onBlur={() => setOpen(false)}
      >
        {kind === "estimated" ? <EstimatedIcon /> : <InfoIcon />}
      </button>
      {open && (
        <span role="tooltip" className="photo-date-marker-tooltip">
          {label}
        </span>
      )}
    </span>
  );
}

/** Welche Kennzeichnungen eine Gruppe von Bildern braucht (gemischte Tage möglich). */
export function dateMarkersFor(sources: (string | undefined)[]): { kind: DateMarkerKind; count: number; total: number }[] {
  const total = sources.length;
  const estimated = sources.filter((source) => source === "estimated").length;
  const upload = sources.filter((source) => source === "upload").length;
  const markers: { kind: DateMarkerKind; count: number; total: number }[] = [];
  if (estimated) markers.push({ kind: "estimated", count: estimated, total });
  if (upload) markers.push({ kind: "upload", count: upload, total });
  return markers;
}
