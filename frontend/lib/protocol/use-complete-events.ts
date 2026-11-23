"use client";

import { type Dispatch, type SetStateAction, useEffect } from "react";

import { browserApiFetch } from "@/lib/api/client";
import type { EventSummary } from "@/types/api";

const PAGE_SIZE = 500;

/** Vollständige Liste mit dem lokalen Stand zusammenführen: lokal geänderte oder neu angelegte
 * Termine (Bearbeiten, Mitschreib-Meldungen) gewinnen gegen die geladene Fassung. */
export function mergeEvents(current: EventSummary[], all: EventSummary[]): EventSummary[] {
  const known = new Map(current.map((event) => [event.id, event]));
  const merged = all.map((event) => known.get(event.id) ?? event);
  const loaded = new Set(all.map((event) => event.id));
  for (const event of current) if (!loaded.has(event.id)) merged.push(event);
  return merged.length === current.length && merged.every((event) => known.get(event.id) === event) ? current : merged;
}

async function fetchAllEvents(): Promise<EventSummary[]> {
  const all: EventSummary[] = [];
  for (let skip = 0; ; skip += PAGE_SIZE) {
    const page = await browserApiFetch<EventSummary[]>(`/api/events?skip=${skip}&limit=${PAGE_SIZE}`);
    all.push(...page);
    if (page.length < PAGE_SIZE) return all;
  }
}

/**
 * Lädt die Termine nach, die die Seite für die erste Darstellung weggelassen hat (L5,
 * lib/protocol/initial-editor-data.ts): ältere Termine für Terminauswahl, Kalender und
 * Tag-Vorschläge. Im Leerlauf nach dem ersten Darstellen; Fehler sind still (die Anzeige des
 * Protokolls hat schon alle nötigen Termine).
 */
export function useCompleteEvents(complete: boolean, setEvents: Dispatch<SetStateAction<EventSummary[]>>) {
  useEffect(() => {
    if (complete) return;
    let cancelled = false;
    const load = () => {
      fetchAllEvents()
        .then((all) => {
          if (!cancelled) setEvents((current) => mergeEvents(current, all));
        })
        .catch(() => undefined);
    };
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (idleWindow.requestIdleCallback) {
      const handle = idleWindow.requestIdleCallback(load, { timeout: 3000 });
      return () => {
        cancelled = true;
        idleWindow.cancelIdleCallback?.(handle);
      };
    }
    const timer = window.setTimeout(load, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [complete, setEvents]);
}
