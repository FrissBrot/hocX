"use client";

// Übersteuerung der Elementdarstellung: im Brand Studio gegenüber dem Grundstil, im Designer
// für einen einzelnen Block gegenüber dem Brand-Profil. Leer = geerbter Wert.

import { useTranslations } from "next-intl";

import type { AppearanceCatalog } from "@/lib/documents/api";
import { setAppearance } from "@/lib/documents/appearance";
import type { AppearanceOverrides } from "@/lib/documents/layout";

type Props = {
  catalog: AppearanceCatalog;
  kinds: string[];
  value: AppearanceOverrides | undefined;
  /** Geerbte Variante je Elementart (für die Option «geerbt») */
  inherited: (kind: string) => string;
  /** Beschriftung der geerbten Option, z. B. «Grundstil: Linien» */
  inheritLabel: (value: string) => string;
  onChange: (value: AppearanceOverrides) => void;
};

export function AppearanceEditor({ catalog, kinds, value, inherited, inheritLabel, onChange }: Props) {
  const t = useTranslations("documentStudio");
  return (
    <div className="studio-appearance-list">
      {kinds.map((kind) => {
        const current = value?.[kind];
        const kindLabel = t(`appearance.kind.${kind}`);
        return (
          <div key={kind} className="studio-appearance-row">
            <span className="field-label">{kindLabel}</span>
            <select
              aria-label={kindLabel}
              value={current?.variant ?? ""}
              onChange={(event) => onChange(setAppearance(value, kind, { variant: event.target.value || null }))}
            >
              <option value="">{inheritLabel(t(`appearance.variant.${kind}.${inherited(kind)}`))}</option>
              {(catalog.variants[kind] ?? []).map((variant) => (
                <option key={variant} value={variant}>
                  {t(`appearance.variant.${kind}.${variant}`)}
                </option>
              ))}
            </select>
            {catalog.corner_kinds.includes(kind) ? (
              <select
                aria-label={t("appearance.cornersFor", { kind: kindLabel })}
                value={current?.corners ?? ""}
                onChange={(event) => onChange(setAppearance(value, kind, { corners: (event.target.value || null) as "square" | "rounded" | null }))}
              >
                <option value="">{t("appearance.cornersInherit")}</option>
                <option value="square">{t("appearance.corners.square")}</option>
                <option value="rounded">{t("appearance.corners.rounded")}</option>
              </select>
            ) : (
              <span aria-hidden="true" />
            )}
          </div>
        );
      })}
    </div>
  );
}
