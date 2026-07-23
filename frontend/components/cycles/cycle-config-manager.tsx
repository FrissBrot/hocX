"use client";

import { useState } from "react";
import { DataToolbar } from "@/components/ui/data-table";
import { browserApiFetch } from "@/lib/api/client";
import { CycleConfigSummary } from "@/types/api";
import { formatCycleName } from "@/lib/utils/cycle";

const MONTH_NAMES = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

type CycleConfigForm = {
  name: string;
  reset_month: string;
  reset_day: string;
  name_pattern: string;
};

const emptyForm: CycleConfigForm = {
  name: "",
  reset_month: "7",
  reset_day: "31",
  name_pattern: "",
};

function cyclePreview(form: CycleConfigForm): string {
  const today = new Date();
  const year =
    today.getMonth() + 1 > Number(form.reset_month) ? today.getFullYear() : today.getFullYear() - 1;
  return form.name_pattern ? formatCycleName(form.name_pattern, year) : `${year}/${year + 1}`;
}

function resetLabel(day: string, month: string): string {
  const m = Number(month);
  const monthName = MONTH_NAMES[(m - 1) % 12] ?? "";
  return `${day}. ${monthName}`;
}

function CycleForm({
  form,
  setForm,
  onSubmit,
  submitLabel,
  error,
  saving,
  onCancel,
}: {
  form: CycleConfigForm;
  setForm: (f: CycleConfigForm) => void;
  onSubmit: (e: React.FormEvent) => Promise<void>;
  submitLabel: string;
  error: string | null;
  saving: boolean;
  onCancel?: () => void;
}) {
  return (
    <form onSubmit={(e) => void onSubmit(e)}>
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">Name</span>
          <input
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="z.B. Scharjahr"
          />
          <span className="field-help">Interne Bezeichnung dieser Zyklus-Konfiguration.</span>
        </label>

        <div className="two-col" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <label className="field-stack">
            <span className="field-label">Reset-Monat</span>
            <input
              type="number"
              min={1}
              max={12}
              required
              value={form.reset_month}
              onChange={(e) => setForm({ ...form, reset_month: e.target.value })}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Reset-Tag</span>
            <input
              type="number"
              min={1}
              max={31}
              required
              value={form.reset_day}
              onChange={(e) => setForm({ ...form, reset_day: e.target.value })}
            />
          </label>
        </div>
        <p className="field-help" style={{ marginTop: "-6px" }}>
          Neuer Zyklus beginnt nach diesem Datum — z.&nbsp;B. 31.&nbsp;Juli → Start 1.&nbsp;August.
        </p>

        <label className="field-stack">
          <span className="field-label">Namens-Muster</span>
          <input
            value={form.name_pattern}
            onChange={(e) => setForm({ ...form, name_pattern: e.target.value })}
            placeholder="z.B. Scharjahr [cy]/[cy_end]"
          />
          <span className="field-help">
            <code style={{ fontSize: "0.82em" }}>[cy]</code> = Startjahr,{" "}
            <code style={{ fontSize: "0.82em" }}>[cy_end]</code> = Endjahr. Ohne Muster: 2025/2026.
            &nbsp;Vorschau: <strong>{cyclePreview(form)}</strong>
          </span>
        </label>

        {error && <div className="form-error-banner">{error}</div>}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: "10px",
            paddingTop: "4px",
          }}
        >
          {onCancel && (
            <button type="button" className="button-ghost" onClick={onCancel}>
              Abbrechen
            </button>
          )}
          <button type="submit" className="button-inline" disabled={saving}>
            {saving ? "Wird gespeichert…" : submitLabel}
          </button>
        </div>
      </div>
    </form>
  );
}

export function CycleConfigManager({ initialConfigs }: { initialConfigs: CycleConfigSummary[] }) {
  const [configs, setConfigs] = useState(initialConfigs);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CycleConfigForm>(emptyForm);
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<CycleConfigForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function openEdit(cfg: CycleConfigSummary) {
    setEditId(cfg.id);
    setEditForm({
      name: cfg.name,
      reset_month: String(cfg.reset_month),
      reset_day: String(cfg.reset_day),
      name_pattern: cfg.name_pattern ?? "",
    });
    setEditError(null);
    setShowCreate(false);
  }

  function cancelEdit() {
    setEditId(null);
    setEditError(null);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setCreateError(null);
    try {
      const created = await browserApiFetch<CycleConfigSummary>("/api/cycle-configs", {
        method: "POST",
        body: JSON.stringify({
          name: createForm.name.trim(),
          reset_month: Number(createForm.reset_month),
          reset_day: Number(createForm.reset_day),
          name_pattern: createForm.name_pattern.trim() || null,
        }),
      });
      setConfigs((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setCreateForm(emptyForm);
      setShowCreate(false);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Fehler beim Erstellen");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (editId === null) return;
    setSaving(true);
    setEditError(null);
    try {
      const updated = await browserApiFetch<CycleConfigSummary>(`/api/cycle-configs/${editId}`, {
        method: "PUT",
        body: JSON.stringify({
          name: editForm.name.trim(),
          reset_month: Number(editForm.reset_month),
          reset_day: Number(editForm.reset_day),
          name_pattern: editForm.name_pattern.trim() || null,
        }),
      });
      setConfigs((prev) =>
        prev.map((c) => (c.id === editId ? updated : c)).sort((a, b) => a.name.localeCompare(b.name))
      );
      setEditId(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "Fehler beim Speichern");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (
      !confirm(
        "Zyklus-Konfiguration löschen? Nur möglich solange kein Template zugeordnet ist."
      )
    )
      return;
    setDeleteError(null);
    try {
      await browserApiFetch(`/api/cycle-configs/${id}`, { method: "DELETE" });
      setConfigs((prev) => prev.filter((c) => c.id !== id));
      if (editId === id) setEditId(null);
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "Fehler beim Löschen");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Zyklen"
        description="Zyklus-Definitionen verwalten und Protokoll-Templates zuordnen."
        actions={
          !showCreate && editId === null ? (
            <button
              type="button"
              className="button-inline"
              onClick={() => {
                setShowCreate(true);
                setCreateError(null);
              }}
            >
              + Neuer Zyklus
            </button>
          ) : undefined
        }
      />

      {/* Create form */}
      {showCreate && (
        <div className="card">
          <div className="eyebrow">Neuer Zyklus</div>
          <CycleForm
            form={createForm}
            setForm={setCreateForm}
            onSubmit={handleCreate}
            submitLabel="Zyklus erstellen"
            error={createError}
            saving={saving}
            onCancel={() => {
              setShowCreate(false);
              setCreateError(null);
            }}
          />
        </div>
      )}

      {/* Delete error banner */}
      {deleteError && <div className="form-error-banner">{deleteError}</div>}

      {/* Config list */}
      {configs.length === 0 && !showCreate ? (
        <div
          style={{
            padding: "32px 24px",
            borderRadius: "20px",
            border: "1px dashed var(--border)",
            color: "var(--muted)",
            textAlign: "center",
          }}
        >
          Noch keine Zyklen konfiguriert.
        </div>
      ) : (
        <div className="responsibility-list">
          {configs.map((cfg) => (
            <div key={cfg.id} className="responsibility-card">
              {editId === cfg.id ? (
                <>
                  <div className="eyebrow">Zyklus bearbeiten</div>
                  <CycleForm
                    form={editForm}
                    setForm={setEditForm}
                    onSubmit={handleSave}
                    submitLabel="Speichern"
                    error={editError}
                    saving={saving}
                    onCancel={cancelEdit}
                  />
                </>
              ) : (
                <div className="responsibility-card-head">
                  <div style={{ display: "grid", gap: "4px" }}>
                    <strong style={{ fontSize: "1rem" }}>{cfg.name}</strong>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        flexWrap: "wrap",
                        fontSize: "0.84rem",
                        color: "var(--muted)",
                      }}
                    >
                      <span>Reset {resetLabel(String(cfg.reset_day), String(cfg.reset_month))}</span>
                      <span style={{ opacity: 0.4 }}>·</span>
                      <span>
                        Aktuell:{" "}
                        <strong style={{ color: "var(--text)", fontWeight: 600 }}>
                          {formatCycleName(cfg.name_pattern, new Date().getFullYear() - 1)}
                        </strong>
                      </span>
                      {cfg.name_pattern && (
                        <>
                          <span style={{ opacity: 0.4 }}>·</span>
                          <code
                            style={{
                              fontSize: "0.78em",
                              padding: "1px 6px",
                              borderRadius: "6px",
                              background: "color-mix(in srgb, var(--muted) 12%, transparent 88%)",
                              border: "1px solid color-mix(in srgb, var(--muted) 18%, transparent 82%)",
                            }}
                          >
                            {cfg.name_pattern}
                          </code>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="responsibility-card-actions">
                    <button className="button-ghost" onClick={() => openEdit(cfg)}>
                      Bearbeiten
                    </button>
                    <button
                      className="button-ghost button-icon button-icon-danger"
                      title="Löschen"
                      onClick={() => void handleDelete(cfg.id)}
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M2 4h12M5 4V2h6v2M6 7v5M10 7v5M3 4l1 9a1 1 0 001 1h6a1 1 0 001-1l1-9" />
                      </svg>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
