"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

type CsvPreviewRow = { display_name: string; first_name: string | null; last_name: string | null; email: string | null };
type ImportResult = { imported: ParticipantSummary[]; duplicates: string[]; errors: string[] };

function parseCsvForPreview(text: string): CsvPreviewRow[] {
  const normalized = text.replace(/^\uFEFF/, "");
  const lines = normalized.split(/\r?\n/);
  const firstLine = lines[0] ?? "";
  const delimiter = firstLine.split(";").length > firstLine.split(",").length ? ";" : ",";
  const headers = firstLine.split(delimiter).map((h) => h.trim());
  const rows: CsvPreviewRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const cells = line.split(delimiter);
    const get = (name: string) => (cells[headers.indexOf(name)] ?? "").trim() || null;
    const first_name = get("Vorname");
    const last_name = get("Nachname");
    const nickname = get("Übername");
    const company_name = get("Firmenname");
    const email = get("Haupt-E-Mail");
    const display_name = nickname ?? ([first_name, last_name].filter(Boolean).join(" ") || null) ?? company_name;
    if (!display_name) continue;
    rows.push({ display_name, first_name, last_name, email });
  }
  return rows;
}

type ParticipantManagerProps = {
  initialParticipants: ParticipantSummary[];
  templates: TemplateSummary[];
};

type ParticipantFormState = {
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  is_active: boolean;
};

const emptyForm: ParticipantFormState = {
  first_name: "",
  last_name: "",
  display_name: "",
  email: "",
  is_active: true,
};

export function ParticipantManager({ initialParticipants, templates }: ParticipantManagerProps) {
  const [participants, setParticipants] = useState(initialParticipants);
  const [selectedParticipant, setSelectedParticipant] = useState<ParticipantSummary | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [form, setForm] = useState<ParticipantFormState>(emptyForm);
  const [selectedParticipantIds, setSelectedParticipantIds] = useState<number[]>([]);
  const [assignedTemplateIds, setAssignedTemplateIds] = useState<number[]>([]);
  const [csvPreview, setCsvPreview] = useState<{ rows: CsvPreviewRow[]; file: File } | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

  const filteredParticipants = useMemo(
    () =>
      participants.filter((participant) => {
        const haystack = `${participant.display_name} ${participant.first_name ?? ""} ${participant.last_name ?? ""} ${participant.email ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [participants, search]
  );

  function openCreate() {
    setSelectedParticipant(null);
    setForm(emptyForm);
    setAssignedTemplateIds([]);
    setShowModal(true);
  }

  async function openEdit(participant: ParticipantSummary) {
    setSelectedParticipant(participant);
    setForm({
      first_name: participant.first_name ?? "",
      last_name: participant.last_name ?? "",
      display_name: participant.display_name,
      email: participant.email ?? "",
      is_active: participant.is_active,
    });
    try {
      const assignedTemplates = await browserApiFetch<TemplateSummary[]>(`/api/participants/${participant.id}/templates`);
      setAssignedTemplateIds(assignedTemplates.map((template) => template.id));
    } catch {
      setAssignedTemplateIds([]);
    }
    setShowModal(true);
  }

  async function saveParticipant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(selectedParticipant ? "Updating participant..." : "Creating participant...");
    setStatusTone("neutral");

    try {
      const payload = {
        first_name: form.first_name || null,
        last_name: form.last_name || null,
        display_name: form.display_name,
        email: form.email || null,
        is_active: form.is_active,
      };

      let participantId: number;
      let updatedParticipant: ParticipantSummary;

      if (selectedParticipant) {
        updatedParticipant = await browserApiFetch<ParticipantSummary>(`/api/participants/${selectedParticipant.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        participantId = updatedParticipant.id;
        setParticipants((current) => current.map((item) => (item.id === updatedParticipant.id ? updatedParticipant : item)));
        setStatus(`Updated ${updatedParticipant.display_name}`);
      } else {
        updatedParticipant = await browserApiFetch<ParticipantSummary>("/api/participants", {
          method: "POST",
          body: JSON.stringify({ tenant_id: 1, ...payload }),
        });
        participantId = updatedParticipant.id;
        setParticipants((current) => [updatedParticipant, ...current]);
        setStatus(`Created ${updatedParticipant.display_name}`);
      }

      await browserApiFetch(`/api/participants/${participantId}/templates`, {
        method: "PUT",
        body: JSON.stringify({ template_ids: assignedTemplateIds }),
      });

      setStatusTone("success");
      setShowModal(false);
      setSelectedParticipant(null);
      setForm(emptyForm);
      setAssignedTemplateIds([]);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Participant could not be saved");
      setStatusTone("error");
    }
  }

  async function deleteParticipant(participantId: number) {
    setStatus(`Deleting participant #${participantId}...`);
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/participants/${participantId}`, { method: "DELETE" });
      setParticipants((current) => current.filter((participant) => participant.id !== participantId));
      setSelectedParticipantIds((current) => current.filter((id) => id !== participantId));
      setStatus(`Deleted participant #${participantId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Participant could not be deleted");
      setStatusTone("error");
    }
  }

  async function bulkDeleteParticipants() {
    if (!selectedParticipantIds.length) {
      return;
    }
    setStatus(`Deleting ${selectedParticipantIds.length} participants...`);
    setStatusTone("neutral");
    try {
      await browserApiFetch("/api/participants", {
        method: "DELETE",
        body: JSON.stringify({ participant_ids: selectedParticipantIds }),
      });
      setParticipants((current) => current.filter((participant) => !selectedParticipantIds.includes(participant.id)));
      setSelectedParticipantIds([]);
      setStatus("Participants deleted");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Participants could not be deleted");
      setStatusTone("error");
    }
  }

  async function handleCsvFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const text = await file.text();
    const rows = parseCsvForPreview(text);
    setCsvPreview({ rows, file });
  }

  async function confirmCsvImport() {
    if (!csvPreview) return;
    setImporting(true);
    try {
      const body = new FormData();
      body.append("file", csvPreview.file);
      const result = await browserApiFetch<ImportResult>("/api/participants/import-csv", {
        method: "POST",
        body,
      });
      setParticipants((current) => [...result.imported, ...current]);
      setCsvPreview(null);
      setImportResult(result);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "CSV import failed");
      setStatusTone("error");
      setCsvPreview(null);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Teilnehmer"
        description="Mandantenweite Personen, die spaeter Templates und Todos zugeordnet werden koennen."
        actions={
          <div className="table-toolbar-actions">
            <label className="button-inline button-ghost participant-import-button">
              CSV import
              <input type="file" accept=".csv,text/csv" onChange={(e) => void handleCsvFileSelected(e)} hidden />
            </label>
            <button
              type="button"
              className="button-inline button-danger"
              onClick={() => void bulkDeleteParticipants()}
              disabled={selectedParticipantIds.length === 0}
            >
              Bulk delete
            </button>
            <button type="button" className="button-inline" onClick={openCreate}>
              Neuer Teilnehmer
            </button>
          </div>
        }
      />

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Search</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search participants" />
          </label>
          <div className="card">
            <div className="eyebrow">Überblick</div>
            <div className="status-row">
              <span className="pill">{selectedParticipantIds.length} ausgewählt</span>
              <span className="pill">{filteredParticipants.length} sichtbar</span>
              <span className="pill">{participants.length} gesamt</span>
            </div>
          </div>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["", "Teilnehmer", "Vorname", "Nachname", "E-Mail", "Status", "Actions"]} emptyMessage="Keine Teilnehmer für den aktuellen Filter gefunden.">
        {filteredParticipants.map((participant) => {
          const isSelected = selectedParticipantIds.includes(participant.id);
          return (
            <tr key={participant.id} className="table-row-clickable" onClick={() => void openEdit(participant)}>
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(event) =>
                    setSelectedParticipantIds((current) =>
                      event.target.checked ? [...current, participant.id] : current.filter((id) => id !== participant.id)
                    )
                  }
                />
              </td>
              <td>
                <strong>{participant.display_name}</strong>
                <div className="muted">
                  {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || (participant.email ?? "Teilnehmer")}
                </div>
              </td>
              <td>{participant.first_name ?? "—"}</td>
              <td>{participant.last_name ?? "—"}</td>
              <td>{participant.email ?? "—"}</td>
              <td><span className="pill">{participant.is_active ? "Aktiv" : "Inaktiv"}</span></td>
              <td>
                <div className="table-actions">
                  <button
                    type="button"
                    className="button-inline button-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteParticipant(participant.id);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          );
        })}
      </DataTable>

      {/* CSV preview modal */}
      <Modal
        open={csvPreview !== null}
        onClose={() => setCsvPreview(null)}
        title="CSV-Vorschau"
        description={`${csvPreview?.rows.length ?? 0} Einträge erkannt. Nur Vorname, Nachname, Übername und E-Mail werden importiert.`}
      >
        <div className="grid">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border-strong)" }}>Anzeigename</th>
                  <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border-strong)" }}>Vorname</th>
                  <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border-strong)" }}>Nachname</th>
                  <th style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--border-strong)" }}>E-Mail</th>
                </tr>
              </thead>
              <tbody>
                {(csvPreview?.rows ?? []).map((row, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "6px 10px" }}><strong>{row.display_name}</strong></td>
                    <td style={{ padding: "6px 10px" }}>{row.first_name ?? <span className="muted">—</span>}</td>
                    <td style={{ padding: "6px 10px" }}>{row.last_name ?? <span className="muted">—</span>}</td>
                    <td style={{ padding: "6px 10px" }}>{row.email ?? <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-inline button-ghost" onClick={() => setCsvPreview(null)}>Abbrechen</button>
            <button type="button" className="button-inline" onClick={() => void confirmCsvImport()} disabled={importing}>
              {importing ? "Importiere…" : `${csvPreview?.rows.length ?? 0} Einträge importieren`}
            </button>
          </div>
        </div>
      </Modal>

      {/* Import result modal */}
      <Modal
        open={importResult !== null}
        onClose={() => setImportResult(null)}
        title="Import abgeschlossen"
        description=""
      >
        {importResult && (
          <div className="grid">
            <div className="status-row">
              <span className="pill" style={{ background: "var(--success)", color: "#fff" }}>
                {importResult.imported.length} importiert
              </span>
              {importResult.duplicates.length > 0 && (
                <span className="pill" style={{ background: "var(--warning)", color: "#fff" }}>
                  {importResult.duplicates.length} Duplikate übersprungen
                </span>
              )}
              {importResult.errors.length > 0 && (
                <span className="pill" style={{ background: "var(--danger)", color: "#fff" }}>
                  {importResult.errors.length} Fehler
                </span>
              )}
            </div>
            {importResult.duplicates.length > 0 && (
              <div>
                <div className="field-label">Übersprungen (bereits vorhanden)</div>
                <div className="muted" style={{ fontSize: "0.85rem", lineHeight: 1.7 }}>
                  {importResult.duplicates.join(", ")}
                </div>
              </div>
            )}
            {importResult.errors.length > 0 && (
              <div>
                <div className="field-label">Fehler</div>
                <div className="muted" style={{ fontSize: "0.85rem", lineHeight: 1.7 }}>
                  {importResult.errors.map((e, i) => <div key={i}>{e}</div>)}
                </div>
              </div>
            )}
            <div className="table-toolbar-actions">
              <button type="button" className="button-inline" onClick={() => setImportResult(null)}>Schließen</button>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit/Create modal */}
      <Modal
        open={showModal}
        onClose={() => setShowModal(false)}
        title={selectedParticipant ? "Teilnehmer bearbeiten" : "Teilnehmer erstellen"}
        description="Teilnehmer koennen direkt Templates zugewiesen und spaeter in Todos ausgewaehlt werden."
      >
        <form className="grid" onSubmit={saveParticipant}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Anzeigename</span>
              <input value={form.display_name} onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))} required />
            </label>
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
              />
              Aktiv
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Vorname</span>
              <input value={form.first_name} onChange={(event) => setForm((current) => ({ ...current, first_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Nachname</span>
              <input value={form.last_name} onChange={(event) => setForm((current) => ({ ...current, last_name: event.target.value }))} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} />
          </label>
          <div className="field-stack">
            <span className="field-label">Templates</span>
            <div className="participant-check-grid">
              {templates.map((template) => {
                const checked = assignedTemplateIds.includes(template.id);
                return (
                  <label key={template.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        setAssignedTemplateIds((current) =>
                          event.target.checked ? [...new Set([...current, template.id])] : current.filter((id) => id !== template.id)
                        )
                      }
                    />
                    <div>
                      <strong>{template.name}</strong>
                      <div className="muted">{template.description ?? "Kein Beschreibungstext"}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">
              {selectedParticipant ? "Save participant" : "Create participant"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
