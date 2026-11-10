"use client";

import { createContext, useContext, useMemo } from "react";
import type { ParticipantSummary } from "@/types/api";

/** Alle Teilnehmer des Mandanten – nur zur Namensauflösung, nicht für Auswahllisten. */
export const ParticipantDirectoryContext = createContext<ParticipantSummary[]>([]);

/** Ergänzt die auswählbaren Teilnehmer um alle übrigen, damit gespeicherte Referenzen ausserhalb der Vorlage trotzdem mit Namen erscheinen. */
export function useParticipantNameSource(participants: ParticipantSummary[]) {
  const directory = useContext(ParticipantDirectoryContext);
  return useMemo(() => {
    if (!directory.length) return participants;
    const knownIds = new Set(participants.map((participant) => participant.id));
    return [...participants, ...directory.filter((participant) => !knownIds.has(participant.id))];
  }, [participants, directory]);
}
