import { browserApiFetch } from "@/lib/api/client";
import type { AttendanceFine } from "@/types/api";

// Automatische Anwesenheits-Bussen (Verspaetet/Unentschuldigt) - gemeinsam fuer den Desktop-
// Editor (focused-element-editor.tsx) und den mobilen Editor, damit beide exakt dieselben
// Bussen anlegen/entfernen. Vorher stand diese Logik nur inline im Desktop-Editor.

export type AttendanceFineConfig = {
  accountId: string | null;
  amountLate: number;
  amountAbsent: number;
  /** Nur mit Konto und mindestens einem Betrag > 0 werden ueberhaupt Bussen erzeugt. */
  enabled: boolean;
};

export function attendanceFineConfig(blockConfig: Record<string, unknown>): AttendanceFineConfig {
  const accountId = blockConfig.fine_account_id ? String(blockConfig.fine_account_id) : null;
  const amountLate = Number(blockConfig.fine_amount_late ?? 0);
  const amountAbsent = Number(blockConfig.fine_amount_absent ?? 0);
  return { accountId, amountLate, amountAbsent, enabled: accountId != null && (amountLate > 0 || amountAbsent > 0) };
}

/**
 * Gleicht die offene Busse eines Teilnehmers an seinen neuen Anwesenheitsstatus an:
 * "late"/"absent" legen die passende Busse an (eine andersartige offene wird ersetzt), jeder
 * andere Status entfernt eine offene Busse. Fehler werden weitergeworfen - der Aufrufer setzt
 * dann den Anwesenheitsstatus zurueck.
 */
export async function syncAttendanceFine({
  protocolId,
  participant,
  status,
  config,
  fines,
  onRemoved,
  onCreated,
}: {
  protocolId: string;
  participant: { id: string; display_name: string };
  status: string;
  config: AttendanceFineConfig;
  fines: AttendanceFine[];
  onRemoved: (fineId: string) => void;
  onCreated: (fine: AttendanceFine) => void;
}): Promise<void> {
  if (!config.enabled) return;
  const existingFine = fines.find(
    (fine) => fine.participant_id === participant.id && (fine.fine_type === "late" || fine.fine_type === "absent") && fine.status === "pending"
  );
  const wanted = status === "late" && config.amountLate > 0 ? "late" : status === "absent" && config.amountAbsent > 0 ? "absent" : null;

  if (!wanted) {
    if (existingFine) {
      await browserApiFetch(`/api/fines/${existingFine.id}`, { method: "DELETE" });
      onRemoved(existingFine.id);
    }
    return;
  }
  if (existingFine?.fine_type === wanted) return;
  if (existingFine) {
    await browserApiFetch(`/api/fines/${existingFine.id}`, { method: "DELETE" });
    onRemoved(existingFine.id);
  }
  const created = await browserApiFetch<AttendanceFine>("/api/fines", {
    method: "POST",
    body: JSON.stringify({
      protocol_id: protocolId,
      participant_id: participant.id,
      participant_name_snapshot: participant.display_name,
      fine_type: wanted,
      amount: wanted === "late" ? config.amountLate : config.amountAbsent,
      account_id: config.accountId,
    }),
  });
  if (created) onCreated(created);
}
