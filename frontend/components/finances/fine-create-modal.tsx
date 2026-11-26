"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { financeErrorMessage } from "@/components/finances/finance-errors";
import { AttendanceFine, FinanceAccount, ParticipantSummary, ProtocolSummary } from "@/types/api";
import { Select } from "@/components/ui/select";

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
          showToast(financeErrorMessage(error, t, "loadOptionsFailed"), "error");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [open, showToast, t]);

  const isParticipantSelectable = useParticipantSelectable(protocols.find((p) => p.id === protocolId)?.protocol_date);
  const participant = participants.find((entry) => entry.id === participantId) ?? null;
  const parsedAmount = Number(amount.replace(",", "."));
  const canSave = !!protocolId && !!participant && isParticipantSelectable(participant) && !!accountId && Number.isFinite(parsedAmount) && parsedAmount > 0 && !saving;

  /** Übersetzte Meldung statt Backend-Text (dieser war nur deutsch und nannte den Typ roh, z. B. 'absent'). */
  function createErrorMessage(error: unknown, name: string, type: string): string {
    const detail = (error as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && (detail as { code?: unknown }).code === "duplicate_fine") {
      return t("createFineDuplicate", { name, type });
    }
    return financeErrorMessage(error, t, "createFineFailed");
  }

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
      showToast(createErrorMessage(error, participant.display_name, fineTypeLabel[fineType] ?? fineType), "error");
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
            isOptionSelectable={isParticipantSelectable}
            getId={(entry) => entry.id}
            getLabel={(entry) => entry.display_name}
            value={participantId}
            onChange={(entry) => setParticipantId(entry?.id ?? null)}
            placeholder={t("participantPlaceholder")}
          />
        </div>
        <label className="field-stack">
          <span className="field-label">{t("reasonLabel")}</span>
          <Select value={fineType} onChange={(event) => setFineType(event.target.value as "late" | "absent")}>
            {Object.entries(fineTypeLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </Select>
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
