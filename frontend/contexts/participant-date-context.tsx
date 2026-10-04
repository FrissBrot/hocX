"use client";

import { createContext, useCallback, useContext } from "react";
import { localDateToday, participantEligibleOn } from "@/lib/utils/participant-membership";

export const ParticipantDateContext = createContext<string | null>(null);

/** Anzeige behält alle Referenzen, nur neue Auswahlen werden nach Datum gefiltert. */
export function useParticipantSelectable(asOfOverride?: string | null) {
  const contextDate = useContext(ParticipantDateContext);
  const asOf = asOfOverride ?? contextDate ?? localDateToday();
  return useCallback((participant: { joined_at?: string | null; left_at?: string | null }) =>
    participantEligibleOn(participant, asOf), [asOf]);
}
