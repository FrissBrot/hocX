"use client";

import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { SimilarityGroup, SimilarityGroupList } from "@/types/api";

// Die Gruppen der Tabs "Duplikate" und "Ähnliche" berechnet der Server im Hintergrund
// (photo_similarity_refresh); hier wird das Ergebnis nur abgerufen. Das letzte Ergebnis je Art
// und Filter bleibt zusätzlich für die Sitzung im Speicher, damit ein Tabwechsel es sofort zeigt
// und still aktualisiert. Lokale Änderungen (Löschen, beste Wahl) schreiben mit.
type Kind = "duplicate" | "series";
type Status = SimilarityGroupList["status"];
type Entry = { status: Status; computedAt: string | null; groups: SimilarityGroup[] };

// Solange der Server noch nichts berechnet hat: so oft nachfragen.
export const SIMILARITY_PENDING_POLL_MS = 10_000;

const cache = new Map<string, Entry>();

/** Beim Abmelden leeren - ein anderer Benutzer im selben Tab darf nichts davon sehen. */
export function clearSimilarityGroupsCache(): void {
  cache.clear();
}

function toEntry(data: SimilarityGroupList | null): Entry {
  return { status: data?.status ?? "ready", computedAt: data?.computed_at ?? null, groups: data?.groups ?? [] };
}

export function useSimilarityGroups(
  kind: Kind,
  search: string,
  tagFilter: string[],
  loadError: string
): {
  groups: SimilarityGroup[] | null;
  setGroups: Dispatch<SetStateAction<SimilarityGroup[] | null>>;
  status: Status | null;
  computedAt: string | null;
  error: string | null;
} {
  const trimmed = search.trim();
  const key = `${kind}|${trimmed}|${tagFilter.join(",")}`;
  const [state, setState] = useState<{ key: string; entry: Entry | null; error: string | null }>(() => ({
    key,
    entry: cache.get(key) ?? null,
    error: null,
  }));
  const keyRef = useRef(key);
  keyRef.current = key;
  const [pollTick, setPollTick] = useState(0);

  useEffect(() => {
    const cached = cache.get(key) ?? null;
    setState((current) => (current.key === key && current.entry === cached ? current : { key, entry: cached, error: null }));
    const params = new URLSearchParams();
    params.set("kind", kind);
    if (trimmed) params.set("search", trimmed);
    tagFilter.forEach((tag) => params.append("tags", tag));
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    browserApiFetch<SimilarityGroupList>(`/api/files/similarity-groups?${params.toString()}`)
      .then((data) => {
        if (keyRef.current !== key) return;
        const entry = toEntry(data);
        cache.set(key, entry);
        setState({ key, entry, error: null });
        if (entry.status === "pending" && !cancelled) timer = setTimeout(() => setPollTick((tick) => tick + 1), SIMILARITY_PENDING_POLL_MS);
      })
      .catch(() => {
        if (keyRef.current !== key) return;
        // Mit Daten aus dem Cache bleibt die Ansicht stehen; nur ohne sie den Fehler zeigen.
        if (cache.has(key)) return;
        setState({ key, entry: null, error: loadError });
      });
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, pollTick]);

  const setGroups = useCallback<Dispatch<SetStateAction<SimilarityGroup[] | null>>>((action) => {
    setState((current) => {
      if (!current.entry) return current;
      const next = typeof action === "function" ? action(current.entry.groups) : action;
      const entry = { ...current.entry, groups: next ?? [] };
      cache.set(current.key, entry);
      return { ...current, entry };
    });
  }, []);

  const current = state.key === key ? state : { entry: cache.get(key) ?? null, error: null };
  return {
    groups: current.entry && current.entry.status === "ready" ? current.entry.groups : null,
    setGroups,
    status: current.entry?.status ?? null,
    computedAt: current.entry?.computedAt ?? null,
    error: current.error,
  };
}
