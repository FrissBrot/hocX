"use client";

import { useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";

export type HealthState = "ok" | "healthy" | "degraded" | "warning" | "critical" | "unknown";

const VARIANTS: Record<HealthState, BadgeVariant> = {
  ok: "success",
  healthy: "success",
  degraded: "info",
  warning: "warning",
  critical: "danger",
  unknown: "neutral",
};

/** Zustand als Badge mit Punkt UND Text - nie nur über Farbe (WCAG 1.4.1). */
export function HealthBadge({ state, label, className }: { state: HealthState; label?: string; className?: string }) {
  const t = useTranslations("common.health");
  return (
    <Badge variant={VARIANTS[state]} dot className={className}>
      {label ?? t(state)}
    </Badge>
  );
}
