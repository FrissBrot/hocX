"use client";

import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import type { EventSummary, ParticipantSummary, ProtocolSummary } from "@/types/api";

// Nachladen fuer die Mobile-Ansichten. Bewusst clientseitig statt in page.tsx, damit die
// Desktop-Ansicht derselben Route keine zusaetzlichen Requests bezahlt.

const PAGE_SIZE = 500;
// Obergrenze gegen Endlosschleifen bei einem fehlerhaften Backend (20 Seiten = 10'000 Eintraege).
const PAGE_LIMIT = 20;

/** Alle Seiten eines paginierten Listen-Endpunkts (`skip`/`limit`, max. 500 pro Seite). */
export async function fetchAllPages<T>(path: string): Promise<T[]> {
  const all: T[] = [];
  const separator = path.includes("?") ? "&" : "?";
  for (let page = 0; page < PAGE_LIMIT; page += 1) {
    const batch = (await browserApiFetch<T[]>(`${path}${separator}skip=${all.length}&limit=${PAGE_SIZE}`)) ?? [];
    all.push(...batch);
    if (batch.length < PAGE_SIZE) break;
  }
  return all;
}

/** Wie useState, startet mit den Server-Daten und ersetzt sie nach dem Mount durch alle Seiten. */
export function useAllPages<T>(path: string, initial: T[] | null) {
  const [items, setItems] = useState<T[]>(initial ?? []);

  useEffect(() => {
    let cancelled = false;
    fetchAllPages<T>(path)
      .then((all) => {
        if (!cancelled) setItems(all);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [path]);

  return [items, setItems] as const;
}

export function useAllEvents(initial: EventSummary[] | null) {
  return useAllPages<EventSummary>("/api/events", initial);
}

export function useParticipants(enabled: boolean, initial?: ParticipantSummary[]) {
  const [participants, setParticipants] = useState<ParticipantSummary[]>(initial ?? []);

  useEffect(() => {
    if (!enabled || (initial && initial.length > 0)) return;
    let cancelled = false;
    browserApiFetch<ParticipantSummary[]>("/api/participants?limit=500")
      .then((list) => {
        if (!cancelled) setParticipants(list ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [enabled, initial]);

  return participants;
}

/** Protokoll je Termin (event_id), fuer den "Protokoll öffnen"-Sprung aus dem Termin-Detail. */
export function useProtocolsByEvent(enabled: boolean): Map<string, ProtocolSummary> {
  const [map, setMap] = useState<Map<string, ProtocolSummary>>(new Map());

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    browserApiFetch<ProtocolSummary[]>("/api/protocols?limit=500")
      .then((list) => {
        if (cancelled) return;
        const next = new Map<string, ProtocolSummary>();
        (list ?? []).forEach((protocol) => {
          if (protocol.event_id) next.set(protocol.event_id, protocol);
        });
        setMap(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return map;
}
