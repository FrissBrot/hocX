"use client";

import { useEffect, useState } from "react";

/**
 * Übergabe von der globalen Suche an die Zielseite (Datei oder Person öffnen). Die Seite bekommt
 * nur die ID im Link (`?open=<uuid>`); Suchtext wie ein Dateiname geht über sessionStorage mit,
 * damit keine Namen in Adresszeile, Verlauf oder Server-Logs landen.
 *
 * Gelöscht wird erst, wenn die Seite den Treffer geöffnet hat: beim ersten Rendern auf dem Handy
 * kann kurz die Desktop-Ansicht montiert sein (ResponsiveView), die Anfrage darf dort nicht
 * verloren gehen.
 */
const KEY = "hocx-search-handoff";

export type OpenRequest = { id: string; search: string };

export function storeSearchHandoff(handoff: OpenRequest): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(handoff));
  } catch {
    // ohne sessionStorage öffnet die Seite den Treffer trotzdem, nur ohne vorbelegte Suche
  }
}

export function readOpenRequest(): OpenRequest | null {
  if (typeof window === "undefined") return null;
  const id = new URLSearchParams(window.location.search).get("open");
  if (!id) return null;
  let search = "";
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(KEY) ?? "null") as OpenRequest | null;
    if (stored && stored.id === id) search = String(stored.search ?? "");
  } catch {
    // ignorieren
  }
  return { id, search };
}

export function clearOpenRequest(): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("open")) return;
  params.delete("open");
  const rest = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // ignorieren
  }
}

/**
 * Öffnet einen Treffer der globalen Suche, sobald er in `items` steht. `onSearch` belegt die
 * Suche der Seite vor (damit der Treffer geladen wird); `onFound` öffnet ihn.
 */
export function useOpenRequest<T extends { id: string }>(items: T[], onFound: (item: T, index: number) => void, onSearch?: (text: string) => void): void {
  const [request, setRequest] = useState<OpenRequest | null>(null);
  useEffect(() => {
    const next = readOpenRequest();
    if (!next) return;
    setRequest(next);
    if (next.search && onSearch) onSearch(next.search);
    // nur beim ersten Anzeigen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!request) return;
    const index = items.findIndex((item) => item.id === request.id);
    if (index < 0) return;
    setRequest(null);
    clearOpenRequest();
    onFound(items[index], index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, request]);
}
