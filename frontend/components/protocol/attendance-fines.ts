import { browserApiFetch } from "@/lib/api/client";
import type { AttendanceFine } from "@/types/api";
import { runSerializedByKey } from "@/lib/utils/serialize-by-key";

// Automatische Anwesenheits-Bussen (Verspaetet/Unentschuldigt) - gemeinsam fuer den Desktop-
// Editor (focused-element-editor.tsx) und den mobilen Editor, damit beide exakt dieselben
// Bussen anlegen/entfernen. Vorher stand diese Logik nur inline im Desktop-Editor.

export type AttendanceFineConfig = {
  accountId: string | null;
  amountLate: number;
  amountAbsent: number;
  /** Tarife haben eigene Beträge (Backend: fine_tariff_amounts): dann bestimmt der Server den Betrag
   * je Person (use_tariff). Die Beträge je Person kommen nie zum Client (Tarif = Personendaten). */
  tariffAmounts: boolean;
  /** Nur mit Konto und mindestens einem Betrag > 0 werden ueberhaupt Bussen erzeugt. */
  enabled: boolean;
};

export function attendanceFineConfig(blockConfig: Record<string, unknown>): AttendanceFineConfig {
  const accountId = blockConfig.fine_account_id ? String(blockConfig.fine_account_id) : null;
  const amountLate = Number(blockConfig.fine_amount_late ?? 0);
  const amountAbsent = Number(blockConfig.fine_amount_absent ?? 0);
  const tariffAmounts = blockConfig.fine_tariff_amounts === true;
  return { accountId, amountLate, amountAbsent, tariffAmounts, enabled: accountId != null && (amountLate > 0 || amountAbsent > 0 || tariffAmounts) };
}

/**
 * Führt Anwesenheitsänderungen derselben Person (key, z. B. "<block>:<teilnehmer>") nacheinander
 * aus. Ein Klick auf eine Karte schaltet zum nächsten Status: wer «Entschuldigt» will, klickt
 * schnell über «Verspätet» hinweg. Liefen beide Änderungen parallel, sah die zweite die Busse
 * der ersten noch nicht und liess sie stehen (Bug 2026-11-08: entschuldigt mit Verspätungsbusse).
 */
export function runAttendanceChangeSerialized<T>(key: string, change: () => Promise<T>): Promise<T> {
  return runSerializedByKey(`attendance:${key}`, change);
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
  /** Aktuelle Bussen des Protokolls; als Funktion, damit eine nachfolgende Änderung (siehe
   * runAttendanceChangeSerialized) die eben angelegte Busse schon sieht. */
  fines: AttendanceFine[] | (() => AttendanceFine[]);
  onRemoved: (fineId: string) => void;
  onCreated: (fine: AttendanceFine) => void;
}): Promise<void> {
  if (!config.enabled) return;
  const currentFines = typeof fines === "function" ? fines() : fines;
  const existingFine = currentFines.find(
    (fine) => fine.participant_id === participant.id && (fine.fine_type === "late" || fine.fine_type === "absent") && fine.status === "pending"
  );
  // Mit Tarif-Beträgen entscheidet der Server (0 = keine Busse, Antwort ohne Inhalt)
  const wanted = status === "late" && (config.tariffAmounts || config.amountLate > 0)
    ? "late"
    : status === "absent" && (config.tariffAmounts || config.amountAbsent > 0) ? "absent" : null;

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
      ...(config.tariffAmounts
        ? { use_tariff: true }
        : { amount: wanted === "late" ? config.amountLate : config.amountAbsent }),
      account_id: config.accountId,
    }),
  });
  if (created) onCreated(created);
}
