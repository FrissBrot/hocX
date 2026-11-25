"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { formatPlaceLabel, PhotoPlace, regionLabel } from "@/lib/photos/places";

import { PhotoActionIcon } from "../photo-action-icon";
import { PhotoPlaceDialog } from "../photo-place-dialog";

export type SearchPlaceHandler = (key: string, label: string, kind: string | null) => void;

function searchTarget(place: PhotoPlace, locale: string): { key: string; kind: string | null; label: string } | null {
  if (!place.key) return null;
  const label = place.name ?? regionLabel(place.locality_name, place.admin1_code, place.country_code, locale) ?? "";
  return { key: place.key, kind: place.name ? place.kind : place.locality_kind, label };
}

/** Ort unter dem Dateinamen der Foto-Ansicht; ein Klick sucht Fotos in der Umgebung. */
export function PhotoViewerPlaceLink({ place, onSearchPlace }: { place: PhotoPlace | null | undefined; onSearchPlace?: SearchPlaceHandler }) {
  const t = useTranslations("photos.places");
  const locale = useLocale();
  const label = formatPlaceLabel(place, t, locale);
  if (!place || !label) return null;
  const target = searchTarget(place, locale);
  if (!onSearchPlace || !target) {
    return (
      <span className="photo-viewer-place" title={label}>
        <PhotoActionIcon name="place" />
        <span className="photo-viewer-place-label">{label}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      className="photo-viewer-place"
      title={t("searchAroundTitle", { place: label })}
      onClick={() => onSearchPlace(target.key, target.label, target.kind)}
    >
      <PhotoActionIcon name="place" />
      <span className="photo-viewer-place-label">{label}</span>
    </button>
  );
}

/** Abschnitt «Ort» der Seitenleiste: Ortsname mit Herkunft, Umgebung zeigen, Ort von Hand setzen
 * (nur ohne GPS, photos.manage). Koordinaten stehen weiter nur unter «Details» (mit Recht). */
export function PhotoViewerPlaceSection({
  fileId,
  place,
  canManage,
  onSearchPlace,
  onChanged,
}: {
  fileId: string;
  place: PhotoPlace | null | undefined;
  canManage: boolean;
  onSearchPlace?: SearchPlaceHandler;
  onChanged: () => void;
}) {
  const t = useTranslations("photos.places");
  const locale = useLocale();
  const [dialogOpen, setDialogOpen] = useState(false);
  const label = formatPlaceLabel(place, t, locale);
  const target = place ? searchTarget(place, locale) : null;
  const canSet = canManage && place?.source !== "gps";
  if (!label && !canSet) return null;
  return (
    <section className="photo-viewer-section" aria-labelledby="pv-place-title">
      <h2 className="photo-viewer-section-title" id="pv-place-title">{t("sectionTitle")}</h2>
      {label ? (
        <p className="photo-viewer-empty">
          <strong>{label}</strong> · {place?.source === "manual" ? t("sourceManual") : t("sourceGps")}
        </p>
      ) : (
        <p className="photo-viewer-empty">{t("none")}</p>
      )}
      <div className="photo-viewer-chips">
        {label && target && onSearchPlace ? (
          <button type="button" className="button-secondary" onClick={() => onSearchPlace(target.key, target.label, target.kind)}>
            {t("searchAround")}
          </button>
        ) : null}
        {canSet ? (
          <button type="button" className="button-secondary" onClick={() => setDialogOpen(true)}>
            {place ? t("change") : t("set")}
          </button>
        ) : null}
      </div>
      {label ? <p className="field-help">{t("attribution")}</p> : null}
      {dialogOpen ? (
        <PhotoPlaceDialog
          open
          fileIds={[fileId]}
          allowClear={place?.source === "manual"}
          onClose={() => setDialogOpen(false)}
          onDone={onChanged}
        />
      ) : null}
    </section>
  );
}
