"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { ProtocolSummary, TemplateSummary } from "@/types/api";

type ProtocolBuilderProps = {
  initialProtocols: ProtocolSummary[];
  templates: TemplateSummary[];
};

type ProtocolFormState = {
  template_id: string;
  protocol_number: string;
  protocol_date: string;
  title: string;
};

function protocolStatusLabel(status: string) {
  switch (status) {
    case "geplant":
      return "Geplant";
    case "vorbereitet":
      return "Vorbereitet";
    case "durchgeführt":
      return "Durchgeführt";
    case "abgeschlossen":
      return "Abgeschlossen";
    default:
      return status;
  }
}

function protocolStatusClassName(status: string) {
  switch (status) {
    case "geplant":
      return "status-pill-planned";
    case "vorbereitet":
      return "status-pill-prepared";
    case "durchgeführt":
      return "status-pill-conducted";
    case "abgeschlossen":
      return "status-pill-completed";
    default:
      return "";
  }
}

export function ProtocolBuilder({ initialProtocols, templates }: ProtocolBuilderProps) {
  const router = useRouter();
  const [protocols, setProtocols] = useState(initialProtocols);
  const [availableTemplates, setAvailableTemplates] = useState(templates);
  const [exportsByProtocol, setExportsByProtocol] = useState<Record<number, { content_url?: string | null; status: string; export_format: string }>>({});
  const [pdfBusyByProtocol, setPdfBusyByProtocol] = useState<Record<number, boolean>>({});
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
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

  const sortedProtocols = useMemo(
    () =>
      [...protocols]
        .filter((protocol) => {
          const haystack = `${protocol.protocol_number} ${protocol.title ?? ""}`.toLowerCase();
          const matchesSearch = !search || haystack.includes(search.toLowerCase());
          const matchesStatus = statusFilter === "all" || protocol.status === statusFilter;
          return matchesSearch && matchesStatus;
        })
        .sort((left, right) => right.id - left.id),
    [protocols, search, statusFilter]
  );

  useEffect(() => {
    let cancelled = false;

    async function loadExports() {
      const entries = await Promise.all(
        protocols.map(async (protocol) => {
          try {
            const latest = await browserApiFetch<{ content_url?: string | null; status: string; export_format: string }>(
              `/api/protocols/${protocol.id}/exports/latest`
            );
            return [protocol.id, latest] as const;
          } catch {
            return [protocol.id, { status: "missing", export_format: "none", content_url: null }] as const;
          }
        })
      );

      if (!cancelled) {
        setExportsByProtocol(Object.fromEntries(entries));
      }
    }

    if (protocols.length > 0) {
      void loadExports();
    } else {
      setExportsByProtocol({});
    }

    return () => {
      cancelled = true;
    };
  }, [protocols]);

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
    setStatus("Creating protocol...");
    setStatusTone("neutral");

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
      setStatus(`Created protocol #${created.id}`);
      setStatusTone("success");
      setForm((current) => ({
        ...current,
        protocol_number: "",
        title: ""
      }));
      setShowCreateForm(false);
      router.push(`/protocols/${created.id}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Protocol creation failed");
      setStatusTone("error");
    }
  }

  async function deleteProtocol(protocolId: number) {
    setStatus(`Deleting protocol #${protocolId}...`);
    setStatusTone("neutral");

    try {
      await browserApiFetch<{ message: string }>(`/api/protocols/${protocolId}`, { method: "DELETE" });
      setProtocols((current) => current.filter((protocol) => protocol.id !== protocolId));
      setStatus(`Deleted protocol #${protocolId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Protocol deletion failed");
      setStatusTone("error");
    }
  }

  async function generateAndOpenPdf(protocolId: number, protocolNumber: string) {
    setPdfBusyByProtocol((current) => ({ ...current, [protocolId]: true }));
    setStatus(`Generating PDF for ${protocolNumber}...`);
    setStatusTone("neutral");

    try {
      const result = await browserApiFetch<{ content_url?: string | null; status: string; export_format: string }>(
        `/api/protocols/${protocolId}/exports/pdf`,
        { method: "POST" }
      );
      setExportsByProtocol((current) => ({ ...current, [protocolId]: result }));
      setStatus(`PDF ready for ${protocolNumber}`);
      setStatusTone("success");

      if (result.content_url) {
        window.open(`${browserApiBaseUrl}${result.content_url}`, "_blank", "noopener,noreferrer");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "PDF export failed");
      setStatusTone("error");
    } finally {
      setPdfBusyByProtocol((current) => ({ ...current, [protocolId]: false }));
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Protocols"
        description="Fast access to planned sessions, preparation states and finished PDF exports."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((current) => !current)}>
            {showCreateForm ? "Close create form" : "New protocol"}
          </button>
        }
      />

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title="Create protocol"
        description="Choose the content template and create a fresh snapshot. Number and title can be generated from the template."
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
            <span className="field-help">The document layout is always taken from the selected template.</span>
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
                <span className="field-label">Protocol number</span>
                <input
                  value={form.protocol_number}
                  onChange={(event) => setForm((current) => ({ ...current, protocol_number: event.target.value }))}
                  placeholder="Erforderlich ohne Template-Muster"
                />
              </label>
            ) : null}
            <label className="field-stack">
              <span className="field-label">Date</span>
              <input
                type="date"
                value={form.protocol_date}
                onChange={(event) => setForm((current) => ({ ...current, protocol_date: event.target.value }))}
                required
              />
            </label>
            {!autoTitle ? (
              <label className="field-stack">
                <span className="field-label">Title</span>
                <input
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                  placeholder="Optional title"
                />
              </label>
            ) : null}
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline" disabled={!form.template_id}>
              Create protocol
            </button>
          </div>
        </form>
      </Modal>

      <article className="card">
        <div className="segment-control">
          <button type="button" className={`segment-button${statusFilter === "all" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("all")}>All</button>
          <button type="button" className={`segment-button${statusFilter === "geplant" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("geplant")}>Geplant</button>
          <button type="button" className={`segment-button${statusFilter === "vorbereitet" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("vorbereitet")}>Vorbereitet</button>
          <button type="button" className={`segment-button${statusFilter === "durchgeführt" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("durchgeführt")}>Durchgeführt</button>
          <button type="button" className={`segment-button${statusFilter === "abgeschlossen" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("abgeschlossen")}>Abgeschlossen</button>
        </div>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Search</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by number or title" />
          </label>
          <div className="card">
            <div className="eyebrow">At a glance</div>
            <div className="status-row">
              <span className="pill">{sortedProtocols.length} visible</span>
              <span className="pill">{protocols.length} total</span>
              <span className="pill">{templates.length} templates</span>
            </div>
          </div>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Protocol", "Title", "Status", "Template", "Date", "PDF", "Actions"]}>
        {sortedProtocols.map((protocol) => (
          <tr key={protocol.id} className="table-row-clickable" onClick={() => router.push(`/protocols/${protocol.id}`)}>
            <td>
              <strong>{protocol.protocol_number}</strong>
              <div className="muted">{protocolStatusLabel(protocol.status)}</div>
            </td>
            <td>
              {protocol.title ?? "Untitled protocol"}
            </td>
            <td><span className={`pill ${protocolStatusClassName(protocol.status)}`}>{protocolStatusLabel(protocol.status)}</span></td>
            <td>
              {templates.find((template) => template.id === protocol.template_id)?.name ?? "Template"}
            </td>
            <td>{formatDate(protocol.protocol_date) || "Kein Datum"}</td>
            <td>
              <button
                type="button"
                className={`pdf-icon-link${pdfBusyByProtocol[protocol.id] ? " pdf-icon-disabled" : ""}`}
                onClick={(event) => {
                  event.stopPropagation();
                  void generateAndOpenPdf(protocol.id, protocol.protocol_number);
                }}
                aria-label={`Generate and open PDF for ${protocol.protocol_number}`}
                title="Generate and open PDF"
                disabled={pdfBusyByProtocol[protocol.id]}
              >
                {pdfBusyByProtocol[protocol.id] ? "..." : "PDF"}
              </button>
            </td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteProtocol(protocol.id);
                  }}
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      {sortedProtocols.length === 0 ? <p className="muted">No protocols found for the current filter.</p> : null}
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
