"use client";

import { ReactNode } from "react";

import { useContentIsMobile } from "@/lib/hooks/use-is-mobile";

/**
 * Rendert pro Seite genau eine der beiden Oberflaechen. Beide bekommen dieselben, auf dem
 * Server geladenen Daten - die URL bleibt identisch, ein geteilter Link funktioniert auf PC
 * und Handy. Seiten ohne Mobile-Variante nutzen das nicht und zeigen ihre normale Ansicht.
 *
 * Der Wechsel zwischen den Varianten mountet die Seite neu. Darum wartet er, solange ein Dialog
 * offen ist oder im Inhalt getippt wird (useContentIsMobile, lib/hooks/use-is-mobile.tsx).
 */
export function ResponsiveView({ mobile, desktop }: { mobile: ReactNode; desktop: ReactNode }) {
  return <>{useContentIsMobile() ? mobile : desktop}</>;
}
