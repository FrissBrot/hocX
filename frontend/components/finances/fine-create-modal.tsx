"use client";

import { FormEvent, useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { FINE_TYPE_LABEL } from "@/lib/constants/fine-types";
import { AttendanceFine, FinanceAccount, ParticipantSummary, ProtocolSummary } from "@/types/api";

type Props = {
  open: boolean;
  accounts: FinanceAccount[];
  onClose: () => void;
  onCreated: () => void;
};

// Manuelle Busse: gleiche API wie die automatische Verbuchung aus der Anwesenheitskontrolle,
// nur dass Protokoll, Person, Grund und Betrag hier von Hand gewählt werden.
export function FineCreateModal({ open, accounts, onClose, onCreated }: Props) {
  const showToast = useToast();
  const [protocols, setProtocols] = useState<ProtocolSummary[]>([]);
  const [participants, setParticipants] = useState<ParticipantSummary[]>([]);
  const [protocolId, setProtocolId] = useState<string | null>(null);
  const [participantId, setParticipantId] = useState<string | null>(null);
  const [fineType, setFineType] = useState<"late" | "absent">("late");
  const [accountId, setAccountId] = useState<string | null>(accounts[0]?.id ?? null);
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const [loadedProtocols, loadedParticipants] = await Promise.all([
          browserApiFetch<ProtocolSummary[]>("/api/protocols?limit=200"),
          browserApiFetch<ParticipantSummary[]>("/api/participants?limit=500"),
        ]);
        if (cancelled) {
          return;
        }
        setProtocols(loadedProtocols ?? []);
        setParticipants((loadedParticipants ?? []).filter((participant) => participant.is_active));
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "Auswahl konnte nicht geladen werden", "error");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [open, showToast]);

  const participant = participants.find((entry) => entry.id === participantId) ?? null;
  const parsedAmount = Number(amount.replace(",", "."));
  const canSave = !!protocolId && !!participant && !!accountId && Number.isFinite(parsedAmount) && parsedAmount > 0 && !saving;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave || !participant) {
      return;
    }
    setSaving(true);
    try {
      await browserApiFetch<AttendanceFine>("/api/fines", {
        method: "POST",
        body: JSON.stringify({
          protocol_id: protocolId,
          participant_id: participant.id,
          participant_name_snapshot: participant.display_name,
          fine_type: fineType,
          amount: parsedAmount,
          account_id: accountId,
        }),
      });
      showToast("Busse erfasst", "success");
      setParticipantId(null);
      setAmount("");
      onCreated();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Busse konnte nicht erfasst werden", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Busse erfassen" description="Eine Busse einem Protokoll und einer Person zuordnen.">
      <form className="grid" onSubmit={save}>
        <div className="field-stack">
          <span className="field-label">Protokoll</span>
          <SearchableSelect
            options={protocols}
            getId={(protocol) => protocol.id}
            getLabel={(protocol) => protocol.title ? `${protocol.protocol_number} · ${protocol.title}` : protocol.protocol_number}
            value={protocolId}
            onChange={(protocol) => setProtocolId(protocol?.id ?? null)}
            placeholder="Protokoll wählen"
          />
        </div>
        <div className="field-stack">
          <span className="field-label">Teilnehmer</span>
          <SearchableSelect
            options={participants}
            getId={(entry) => entry.id}
            getLabel={(entry) => entry.display_name}
            value={participantId}
            onChange={(entry) => setParticipantId(entry?.id ?? null)}
            placeholder="Teilnehmer wählen"
          />
        </div>
        <label className="field-stack">
          <span className="field-label">Grund</span>
          <select value={fineType} onChange={(event) => setFineType(event.target.value as "late" | "absent")}>
            {Object.entries(FINE_TYPE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <div className="field-stack">
          <span className="field-label">Konto</span>
          <SearchableSelect
            options={accounts}
            getId={(account) => account.id}
            getLabel={(account) => account.name}
            value={accountId}
            onChange={(account) => setAccountId(account?.id ?? null)}
            placeholder="Konto wählen"
          />
        </div>
        <label className="field-stack">
          <span className="field-label">Betrag</span>
          <input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>Abbrechen</button>
          <button type="submit" className="button-primary" disabled={!canSave}>Erfassen</button>
        </div>
      </form>
    </Modal>
  );
}
