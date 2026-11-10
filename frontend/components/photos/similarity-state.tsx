"use client";

import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { formatDateTime } from "@/lib/utils/format";
import { SimilarityGroupList } from "@/types/api";

// Höchstzahl der Hintergrundgruppierung je Mandant (backend: MAX_BACKGROUND_GROUPING_IMAGES).
const MAX_BACKGROUND_GROUPING_IMAGES = 10000;

/** Zustand vor den Gruppen: Fehler, noch nicht berechnet, zu viele Fotos oder Laden. Null,
 * sobald Gruppen vorliegen. */
export function SimilarityState({
  status,
  error,
  loading,
}: {
  status: SimilarityGroupList["status"] | null;
  error: string | null;
  loading: string;
}) {
  const t = useTranslations("photos.similarity");
  if (error) return <p className="form-error-banner">{error}</p>;
  if (status === "too_many") return <StatusBanner tone="neutral" message={t("tooMany", { max: MAX_BACKGROUND_GROUPING_IMAGES })} />;
  if (status === "pending") return <p className="muted">{t("pending")}</p>;
  if (status === null) return <p className="muted">{loading}</p>;
  return null;
}

/** Stand der Hintergrundberechnung - neue Fotos erscheinen erst nach dem nächsten Lauf. */
export function SimilarityComputedAt({ computedAt }: { computedAt: string | null }) {
  const t = useTranslations("photos.similarity");
  const locale = useLocale();
  if (!computedAt) return null;
  return <p className="muted photo-series-hint">{t("computedAt", { time: formatDateTime(computedAt, locale) })}</p>;
}
