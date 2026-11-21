import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { HealthBadge, type HealthState } from "@/components/ui/health-badge";

export type StatTileDelta = {
  /** Fertig übersetzter Text, z. B. «+4 % zum Vormonat» */
  text: string;
  direction: "up" | "down" | "flat";
  /** Ob die Richtung gut oder schlecht ist (Farbe nur zusätzlich zum Text/Pfeil) */
  tone: "good" | "bad" | "neutral";
};

/**
 * Kennzahl-Kachel: Label, Wert, optional Vergleich, Status und Link. Ist `href` gesetzt, ist die
 * ganze Kachel ein Link (Tastatur: Tab + Enter). `unavailable` zeigt einen gedämpften Hinweis statt
 * eines Werts (z. B. «Keine Berechtigung» für Support-Admins).
 */
export function StatTile({
  label,
  value,
  delta,
  status,
  statusLabel,
  hint,
  href,
  linkLabel,
  unavailable,
  children,
}: {
  label: string;
  value?: ReactNode;
  delta?: StatTileDelta | null;
  status?: HealthState;
  statusLabel?: string;
  hint?: ReactNode;
  href?: string;
  /** Zugänglicher Name des Links, falls er vom sichtbaren Text abweichen soll */
  linkLabel?: string;
  unavailable?: string;
  children?: ReactNode;
}) {
  const arrow = delta ? (delta.direction === "up" ? "↑" : delta.direction === "down" ? "↓" : "→") : null;
  const body = (
    <>
      <span className="stat-tile-label">{label}</span>
      {unavailable ? (
        <span className="stat-tile-unavailable">{unavailable}</span>
      ) : (
        <span className="stat-tile-value">{value}</span>
      )}
      {status ? <HealthBadge state={status} label={statusLabel} /> : null}
      {delta && !unavailable ? (
        <span className={`stat-tile-delta stat-tile-delta-${delta.tone}`}>
          <span aria-hidden="true">{arrow}</span> {delta.text}
        </span>
      ) : null}
      {hint && !unavailable ? <span className="stat-tile-hint">{hint}</span> : null}
      {children}
    </>
  );
  if (href && !unavailable) {
    return (
      <Link href={href as Route} className="stat-tile stat-tile-link" aria-label={linkLabel}>
        {body}
      </Link>
    );
  }
  return <div className="stat-tile">{body}</div>;
}
