"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { browserApiFetch } from "@/lib/api/client";
import { formatSearchHit, hitShortLabel, PlaceFilter, PlaceSearchHit, PLACE_RADIUS_MAX_KM } from "@/lib/photos/places";

import { PhotoActionIcon } from "./photo-action-icon";

const SUGGEST_DEBOUNCE_MS = 250;
const MIN_QUERY = 3;

export function placeFilterFromHit(hit: PlaceSearchHit, locale: string): PlaceFilter {
  return { key: hit.key, label: hitShortLabel(hit, locale), radiusKm: hit.radius_km, baseRadiusKm: hit.radius_km };
}

/** Treffertyp «Ort» der Fotosuche: passende Orte zur Eingabe als Knöpfe; ein Klick filtert auf
 * Fotos in der Umgebung (näher zuerst). Ein eigener Abruf, unabhängig von der Fotosuche. */
export function PlaceSuggestions({ query, onSelect }: { query: string; onSelect: (hit: PlaceSearchHit) => void }) {
  const t = useTranslations("photos.places");
  const locale = useLocale();
  const [hits, setHits] = useState<PlaceSearchHit[]>([]);
  const trimmed = query.trim();

  useEffect(() => {
    if (trimmed.length < MIN_QUERY) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      browserApiFetch<PlaceSearchHit[]>(`/api/places/search?q=${encodeURIComponent(trimmed)}&limit=4`, { signal: controller.signal })
        .then((data) => setHits(data ?? []))
        .catch(() => {});
    }, SUGGEST_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed]);

  if (trimmed.length < MIN_QUERY || hits.length === 0) return null;
  return (
    <>
      <strong>{t("suggestionsTitle")}</strong>
      {hits.map((hit) => (
        <button key={hit.key} type="button" className="button-pill photos-place-pill" onClick={() => onSelect(hit)}>
          <PhotoActionIcon name="place" />
          {formatSearchHit(hit, t, locale)}
        </button>
      ))}
    </>
  );
}

/** Aktiver Umkreis als Chip: «Umgebung Kandersteg BE · 5 km», «+10 km», entfernen. */
export function PlaceFilterChip({ filter, onWiden, onRemove }: { filter: PlaceFilter; onWiden: () => void; onRemove: () => void }) {
  const t = useTranslations("photos.places");
  return (
    <span className="photos-filter-chip">
      <PhotoActionIcon name="place" />
      {t("filterChip", { place: filter.label, km: filter.radiusKm })}
      {filter.radiusKm < PLACE_RADIUS_MAX_KM ? (
        <button type="button" className="photos-filter-chip-remove photos-place-widen" aria-label={t("widenLabel", { km: 10 })} onClick={onWiden}>
          {t("widen", { km: 10 })}
        </button>
      ) : null}
      <button type="button" className="photos-filter-chip-remove" aria-label={t("removeFilter", { place: filter.label })} onClick={onRemove}>
        <ActionIcon name="close" width={12} height={12} />
      </button>
    </span>
  );
}
