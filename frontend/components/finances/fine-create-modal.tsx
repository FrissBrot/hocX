"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { fineTypeLabels } from "@/lib/constants/fine-types";
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
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const fineTypeLabel = fineTypeLabels(t);
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
          showToast(error instanceof Error ? error.message : t("loadOptionsFailed"), "error");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [open, showToast, t]);

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
      showToast(t("createFineSuccess"), "success");
      setParticipantId(null);
      setAmount("");
      onCreated();
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFineFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("createFineTitle")} description={t("createFineDescription")}>
      <ModalSaveForm className="grid" onSubmit={save}>
        <div className="field-stack">
          <span className="field-label">{t("protocolLabel")}</span>
          <SearchableSelect
            options={protocols}
            getId={(protocol) => protocol.id}
            getLabel={(protocol) => protocol.title ? `${protocol.protocol_number} · ${protocol.title}` : protocol.protocol_number}
            value={protocolId}
            onChange={(protocol) => setProtocolId(protocol?.id ?? null)}
            placeholder={t("protocolPlaceholder")}
          />
        </div>
        <div className="field-stack">
          <span className="field-label">{t("participantLabel")}</span>
          <SearchableSelect
            options={participants}
            getId={(entry) => entry.id}
            getLabel={(entry) => entry.display_name}
            value={participantId}
            onChange={(entry) => setParticipantId(entry?.id ?? null)}
            placeholder={t("participantPlaceholder")}
          />
        </div>
        <label className="field-stack">
          <span className="field-label">{t("reasonLabel")}</span>
          <select value={fineType} onChange={(event) => setFineType(event.target.value as "late" | "absent")}>
            {Object.entries(fineTypeLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <div className="field-stack">
          <span className="field-label">{t("accountLabel")}</span>
          <SearchableSelect
            options={accounts}
            getId={(account) => account.id}
            getLabel={(account) => account.name}
            value={accountId}
            onChange={(account) => setAccountId(account?.id ?? null)}
            placeholder={t("accountPlaceholder")}
          />
        </div>
        <label className="field-stack">
          <span className="field-label">{t("amountLabel")}</span>
          <input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{tCommon("cancel")}</button>
          <button data-modal-save type="submit" className="button-primary" disabled={!canSave}>{t("recordButton")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
