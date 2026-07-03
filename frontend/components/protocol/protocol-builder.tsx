"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useTableSort } from "@/lib/hooks/use-table-sort";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { ProtocolSummary, TemplateSummary } from "@/types/api";
import { protocolStatusClassName, protocolStatusLabel } from "@/components/protocol/protocol-status";

const PAGE_SIZE = 100;

type ProtocolBuilderProps = {
  initialProtocols: ProtocolSummary[];
  templates: TemplateSummary[];
  readOnly?: boolean;
};

type ProtocolFormState = {
  template_id: string;
  protocol_number: string;
  protocol_date: string;
  title: string;
};

export function ProtocolBuilder({ initialProtocols, templates, readOnly = false }: ProtocolBuilderProps) {
  const router = useRouter();
  const [protocols, setProtocols] = useState(initialProtocols);
  const [hasMore, setHasMore] = useState(initialProtocols.length === PAGE_SIZE);

  // When router.refresh() re-renders the server component while already on this page,
  // sync the updated initialProtocols into local state.
  useEffect(() => {
    setProtocols(initialProtocols);
    setHasMore(initialProtocols.length === PAGE_SIZE);
  }, [initialProtocols]);
  const showToast = useToast();
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [availableTemplates, setAvailableTemplates] = useState(templates);
  const [pdfBusyByProtocol, setPdfBusyByProtocol] = useState<Record<number, boolean>>({});
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);
  const menuBtnRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const { sortKey, sortDirection, toggleSort, sortIndicator } = useTableSort<"id" | "protocol_number" | "title" | "status" | "protocol_date">("id", "desc");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [form, setForm] = useState<ProtocolFormState>({
    template_id: templates[0] ? String(templates[0].id) : "",
    protocol_number: "",
    protocol_date: new Date().toISOString().slice(0, 10),
    title: ""
  });
  const selectedTemplate = useMemo(
    () => availableTemplates.find((template) => String(template.id) === form.template_id) ?? null,
    [availableTemplates, form.template_id]
  );
  const autoProtocolNumber = !!selectedTemplate?.protocol_number_pattern?.trim();
  const autoTitle = !!selectedTemplate?.title_pattern?.trim();

  const sortedProtocols = useMemo(() => {
    const dir = sortDirection === "asc" ? 1 : -1;
    return [...protocols]
      .filter((protocol) => {
        const haystack = `${protocol.protocol_number} ${protocol.title ?? ""}`.toLowerCase();
        const matchesSearch = !search || haystack.includes(search.toLowerCase());
        const matchesStatus = statusFilter === "all" || protocol.status === statusFilter;
        return matchesSearch && matchesStatus;
      })
      .sort((a, b) => {
        if (sortKey === "protocol_date") return (a.protocol_date ?? "").localeCompare(b.protocol_date ?? "") * dir;
        if (sortKey === "protocol_number") return (a.protocol_number ?? "").localeCompare(b.protocol_number ?? "") * dir;
        if (sortKey === "title") return (a.title ?? "").localeCompare(b.title ?? "") * dir;
        if (sortKey === "status") return a.status.localeCompare(b.status) * dir;
        return (b.id - a.id) * dir;
      });
  }, [protocols, search, statusFilter, sortKey, sortDirection]);

  useEffect(() => {
    if (openMenuId === null) return;
    function handleClick() { setOpenMenuId(null); setMenuPos(null); }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [openMenuId]);

  useEffect(() => {
    if (!showCreateForm) {
      return;
    }
    let cancelled = false;
    async function loadTemplates() {
      try {
        const latestTemplates = await browserApiFetch<TemplateSummary[]>("/api/templates");
        if (cancelled) {
          return;
        }
        setAvailableTemplates(latestTemplates);
        setForm((current) => {
          const stillExists = latestTemplates.some((template) => String(template.id) === current.template_id);
          return {
            ...current,
            template_id: stillExists ? current.template_id : latestTemplates[0] ? String(latestTemplates[0].id) : "",
          };
        });
      } catch {
        // Keep the last known list if refresh fails.
      }
    }
    void loadTemplates();
    return () => {
      cancelled = true;
    };
  }, [showCreateForm]);

  async function createProtocol(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      const created = await browserApiFetch<{ id: number }>("/api/protocols/from-template", {
        method: "POST",
        body: JSON.stringify({
          template_id: Number(form.template_id),
          protocol_number: autoProtocolNumber ? null : form.protocol_number || null,
          protocol_date: form.protocol_date,
          title: autoTitle ? null : form.title || null,
          created_by: null,
          event_id: null
        })
      });

      const full = await browserApiFetch<ProtocolSummary>(`/api/protocols/${created.id}`);
      setProtocols((current) => [full, ...current]);
      showToast(`Created protocol #${created.id}`, "success");
      setForm((current) => ({
        ...current,
        protocol_number: "",
        title: ""
      }));
      setShowCreateForm(false);
      router.push(`/protocols/${created.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Protocol creation failed", "error");
    }
  }

  async function deleteProtocol(protocolId: number) {
    try {
      await browserApiFetch<{ message: string }>(`/api/protocols/${protocolId}`, { method: "DELETE" });
      setProtocols((current) => current.filter((protocol) => protocol.id !== protocolId));
      showToast(`Deleted protocol #${protocolId}`, "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Protocol deletion failed", "error");
    }
  }

  async function generateAndOpenPdf(protocolId: number, protocolNumber: string) {
    setPdfBusyByProtocol((current) => ({ ...current, [protocolId]: true }));

    try {
      const result = await browserApiFetch<{ content_url?: string | null; status: string; export_format: string; version_major?: number | null; version_minor?: number | null }>(
        `/api/protocols/${protocolId}/exports/pdf`,
        { method: "POST" }
      );
      // Update version in local protocol list
      if (result.version_major != null && result.version_minor != null) {
        setProtocols((current) =>
          current.map((p) =>
            p.id === protocolId ? { ...p, version_major: result.version_major!, version_minor: result.version_minor! } : p
          )
        );
      }
      showToast(`PDF ready for ${protocolNumber}`, "success");

      if (result.content_url) {
        window.open(`${browserApiBaseUrl}${result.content_url}`, "_blank", "noopener,noreferrer");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "PDF export failed", "error");
    } finally {
      setPdfBusyByProtocol((current) => ({ ...current, [protocolId]: false }));
    }
  }

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<ProtocolSummary[]>(`/api/protocols?skip=${protocols.length}&limit=${PAGE_SIZE}`);
      setProtocols((current) => [...current, ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch {
      // keep current list on error
    } finally {
      setIsLoadingMore(false);
    }
  }

  async function revertStatus(protocolId: number) {
    try {
      const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocolId}/revert-status`, { method: "POST" });
      setProtocols((current) => current.map((p) => (p.id === protocolId ? updated : p)));
      showToast(`Status zurückgesetzt`, "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Zurücksetzen fehlgeschlagen", "error");
    }
  }

  return (
    <div className="grid">
      <div className="protocol-list-toolbar">
        <div className="segment-control">
          <button type="button" className={`segment-button${statusFilter === "all" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("all")}>Alle</button>
          <button type="button" className={`segment-button${statusFilter === "geplant" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("geplant")}>Geplant</button>
          <button type="button" className={`segment-button${statusFilter === "vorbereitet" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("vorbereitet")}>Vorbereitet</button>
          <button type="button" className={`segment-button${statusFilter === "durchgeführt" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("durchgeführt")}>Durchgeführt</button>
          <button type="button" className={`segment-button${statusFilter === "abgeschlossen" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("abgeschlossen")}>Abgeschlossen</button>
        </div>
        <div className="protocol-list-toolbar-right">
          <input className="protocol-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Suchen…" />
          <span className="muted protocol-count">{sortedProtocols.length} / {protocols.length}</span>
          {!readOnly && (
            <button type="button" className="button-inline" onClick={() => setShowCreateForm((c) => !c)}>
              {showCreateForm ? "Abbrechen" : "+ Protokoll"}
            </button>
          )}
        </div>
      </div>

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title="Protokoll erstellen"
        description="Template auswählen und neues Protokoll anlegen."
      >
        <form className="grid" onSubmit={createProtocol}>
          <label className="field-stack">
            <span className="field-label">Template</span>
            <select
              value={form.template_id}
              onChange={(event) => setForm((current) => ({ ...current, template_id: event.target.value }))}
            >
              {availableTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          {selectedTemplate?.protocol_number_pattern || selectedTemplate?.title_pattern ? (
            <div className="info-note">
              {selectedTemplate.protocol_number_pattern ? `Nummer: ${selectedTemplate.protocol_number_pattern}` : "Nummer: manuell"}{" · "}
              {selectedTemplate.title_pattern ? `Titel: ${selectedTemplate.title_pattern}` : "Titel: manuell"}
            </div>
          ) : null}
          <div className="three-col">
            {!autoProtocolNumber ? (
              <label className="field-stack">
                <span className="field-label">Nummer</span>
                <input
                  value={form.protocol_number}
                  onChange={(event) => setForm((current) => ({ ...current, protocol_number: event.target.value }))}
                  placeholder="Protokollnummer"
                />
              </label>
            ) : null}
            <label className="field-stack">
              <span className="field-label">Datum</span>
              <DateInput value={form.protocol_date} onChange={(value) => setForm((current) => ({ ...current, protocol_date: value }))} required />
            </label>
            {!autoTitle ? (
              <label className="field-stack">
                <span className="field-label">Titel</span>
                <input
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                  placeholder="Optionaler Titel"
                />
              </label>
            ) : null}
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline" disabled={!form.template_id}>
              Erstellen
            </button>
          </div>
        </form>
      </Modal>

      <DataTable columns={[
        { key: "protocol_number", label: "Protokoll", sortable: true, sortDirection: sortIndicator("protocol_number"), onSort: () => toggleSort("protocol_number") },
        { key: "title", label: "Titel", sortable: true, sortDirection: sortIndicator("title"), onSort: () => toggleSort("title") },
        { key: "status", label: "Status", sortable: true, sortDirection: sortIndicator("status"), onSort: () => toggleSort("status") },
        ...(!readOnly ? ["Template" as const] : []),
        { key: "protocol_date", label: "Datum", sortable: true, sortDirection: sortIndicator("protocol_date"), onSort: () => toggleSort("protocol_date") },
        "Aktionen",
      ]}>
        {sortedProtocols.map((protocol) => {
          const isFinal = protocol.status === "abgeschlossen";
          const displayMinor = isFinal ? (protocol.version_final_minor ?? 0) : (protocol.version_minor ?? 0);
          const displayMajor = isFinal ? 1 : 0;
          const versionStr = (displayMajor > 0 || displayMinor > 0) ? `v${displayMajor}.${displayMinor}` : null;
          const menuOpen = openMenuId === protocol.id;
          return (
            <tr key={protocol.id} className="table-row-clickable" onClick={() => router.push(`/protocols/${protocol.id}`)}>
              <td>
                <strong>{protocol.protocol_number}</strong>
              </td>
              <td>{protocol.title ?? "—"}</td>
              <td>
                <div className="status-cell">
                  <span className={`pill ${protocolStatusClassName(protocol.status)}`}>{protocolStatusLabel(protocol.status)}</span>
                  {versionStr && <span className="version-badge">{versionStr}</span>}
                </div>
              </td>
              {!readOnly && (
                <td>{templates.find((t) => t.id === protocol.template_id)?.name ?? "—"}</td>
              )}
              <td>{formatDate(protocol.protocol_date) || "—"}</td>
              <td>
                <div className="protocol-row-actions" onClick={(e) => e.stopPropagation()}>
                  {!readOnly && (
                    <div className="kebab-menu-wrapper">
                      <button
                        type="button"
                        className="kebab-menu-btn"
                        title="Weitere Aktionen"
                        ref={(el) => { menuBtnRefs.current[protocol.id] = el; }}
                        onClick={() => {
                          if (menuOpen) {
                            setOpenMenuId(null);
                            setMenuPos(null);
                          } else {
                            const btn = menuBtnRefs.current[protocol.id];
                            if (btn) {
                              const rect = btn.getBoundingClientRect();
                              setMenuPos({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
                            }
                            setOpenMenuId(protocol.id);
                          }
                        }}
                      >
                        ⋯
                      </button>
                    </div>
                  )}
                  {isFinal ? (
                    <button
                      type="button"
                      className={`pdf-icon-link pdf-icon-link-success${pdfBusyByProtocol[protocol.id] ? " pdf-icon-disabled" : ""}`}
                      onClick={() => void generateAndOpenPdf(protocol.id, protocol.protocol_number)}
                      aria-label={`PDF exportieren für ${protocol.protocol_number}`}
                      title="PDF exportieren"
                      disabled={pdfBusyByProtocol[protocol.id]}
                    >
                      {pdfBusyByProtocol[protocol.id] ? "..." : "PDF"}
                    </button>
                  ) : (
                    <span className="protocol-row-action-spacer" aria-hidden="true" />
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </DataTable>

      {sortedProtocols.length === 0 ? <p className="muted">Keine Protokolle gefunden.</p> : null}

      {hasMore && (
        <div className="load-more-row">
          <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()} disabled={isLoadingMore}>
            {isLoadingMore ? "Lädt…" : `Mehr laden (${protocols.length} geladen)`}
          </button>
        </div>
      )}

      {!readOnly && openMenuId !== null && menuPos !== null && typeof document !== "undefined" && createPortal(
        <div
          className="kebab-menu-dropdown"
          style={{ position: "fixed", top: menuPos.top, right: menuPos.right }}
          onClick={(e) => e.stopPropagation()}
        >
          {(() => {
            const protocol = sortedProtocols.find((p) => p.id === openMenuId);
            if (!protocol) return null;
            const isFinal = protocol.status === "abgeschlossen";
            const canRevert = protocol.status !== "geplant";
            return (
              <>
                {!isFinal && (
                  <button
                    type="button"
                    className="kebab-menu-item"
                    onClick={() => {
                      setOpenMenuId(null);
                      void generateAndOpenPdf(protocol.id, protocol.protocol_number);
                    }}
                    disabled={pdfBusyByProtocol[protocol.id]}
                  >
                    {pdfBusyByProtocol[protocol.id] ? "Generiere…" : "PDF-Vorschau"}
                  </button>
                )}
                {canRevert && (
                  <button
                    type="button"
                    className="kebab-menu-item"
                    onClick={() => {
                      setOpenMenuId(null);
                      void revertStatus(protocol.id);
                    }}
                  >
                    Status zurücksetzen
                  </button>
                )}
                <button
                  type="button"
                  className="kebab-menu-item kebab-menu-item-danger"
                  onClick={() => {
                    setOpenMenuId(null);
                    void deleteProtocol(protocol.id);
                  }}
                >
                  Löschen
                </button>
              </>
            );
          })()}
        </div>,
        document.body
      )}
    </div>
  );
}

type ProtocolOverviewProps = {
  protocol: ProtocolSummary;
};

export function ProtocolOverview({ protocol }: ProtocolOverviewProps) {
  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className={`pill ${protocolStatusClassName(protocol.status)}`}>Status: {protocolStatusLabel(protocol.status)}</span>
        <span className="pill">Template zugewiesen</span>
        <span className="pill">Layout from template snapshot</span>
      </div>

      <article className="card">
        <div className="eyebrow">Overview</div>
        <h3>{protocol.title ?? "Untitled protocol"}</h3>
        <p className="muted">Protocol date: {formatDate(protocol.protocol_date) || "unknown"}</p>
        <p className="muted">Template version snapshot: {protocol.template_version ?? "unknown"}</p>
        <p className="muted">Created at: {formatDateTime(protocol.created_at) || "unknown"}</p>
      </article>
    </div>
  );
}
