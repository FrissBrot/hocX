"use client";

import { useEffect, useRef, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import type { StatisticsOverview } from "@/types/api";

import { statisticsPath } from "./statistics-model";

/**
 * Jahr und Vorjahresvergleich der Statistikseite (Desktop und Mobile). Die erste Auswahl kommt
 * vom Server (initialData), jede Änderung lädt nach; ein veraltetes Ergebnis überschreibt nie
 * ein neueres.
 */
export function useStatisticsOverview(initialData: StatisticsOverview | null, initialYear: number, initialCompare = true) {
  const [year, setYear] = useState(initialYear);
  const [compare, setCompare] = useState(initialCompare);
  const [data, setData] = useState<StatisticsOverview | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    let cancelled = false;
    setLoading(true);
    browserApiFetch<StatisticsOverview>(statisticsPath(year, compare))
      .then((overview) => {
        if (cancelled) return;
        setData(overview);
        setFailed(false);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [year, compare]);

  const years = data?.available_years?.length ? data.available_years : [initialYear];
  // Vergleich nur, wenn es im Vorjahr Daten gibt.
  const canCompare = years.includes(year - 1);

  return { year, setYear, compare: compare && canCompare, setCompare, canCompare, years, data, loading, failed };
}

/** Kennzahlen des laufenden Jahres für die Übersicht (Kopfzeile Desktop, Statistik-Karte Mobile). */
export function useYearOverview(year: number) {
  const [data, setData] = useState<StatisticsOverview | null>(null);
  useEffect(() => {
    let cancelled = false;
    browserApiFetch<StatisticsOverview>(statisticsPath(year, false, true))
      .then((overview) => {
        if (!cancelled) setData(overview);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [year]);
  return data;
}
