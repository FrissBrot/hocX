"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { DocumentTemplate, ProtocolSummary, TemplateSummary } from "@/types/api";

type ProtocolBuilderProps = {
  initialProtocols: ProtocolSummary[];
  templates: TemplateSummary[];
  documentTemplates: DocumentTemplate[];
};

type ProtocolFormState = {
  template_id: string;
  document_template_id: string;
  protocol_number: string;
  protocol_date: string;
  title: string;
};

export function ProtocolBuilder({ initialProtocols, templates, documentTemplates }: ProtocolBuilderProps) {
  const router = useRouter();
  const [protocols, setProtocols] = useState(initialProtocols);
  const [exportsByProtocol, setExportsByProtocol] = useState<Record<number, { content_url?: string | null; status: string; export_format: string }>>({});
  const [pdfBusyByProtocol, setPdfBusyByProtocol] = useState<Record<number, boolean>>({});
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [form, setForm] = useState<ProtocolFormState>({
    template_id: templates[0] ? String(templates[0].id) : "",
    document_template_id: documentTemplates.find((item) => item.is_default)?.id
      ? String(documentTemplates.find((item) => item.is_default)?.id)
      : documentTemplates[0]
        ? String(documentTemplates[0].id)
        : "",
    protocol_number: "",
    protocol_date: new Date().toISOString().slice(0, 10),
    title: ""
  });

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

  async function createProtocol(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating protocol...");
    setStatusTone("neutral");

    try {
      const created = await browserApiFetch<{ id: number }>("/api/protocols/from-template", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: 1,
          template_id: Number(form.template_id),
          document_template_id: form.document_template_id ? Number(form.document_template_id) : null,
          protocol_number: form.protocol_number,
          protocol_date: form.protocol_date,
          title: form.title || null,
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
        description="Fast access to protocol drafts, layouts and PDF output."
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
        description="Choose the content template and document layout, then create a fresh snapshot."
      >
        <form className="grid" onSubmit={createProtocol}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Template</span>
              <select
                value={form.template_id}
                onChange={(event) => setForm((current) => ({ ...current, template_id: event.target.value }))}
              >
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    #{template.id} {template.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-stack">
              <span className="field-label">Document layout</span>
              <select
                value={form.document_template_id}
                onChange={(event) => setForm((current) => ({ ...current, document_template_id: event.target.value }))}
              >
                {documentTemplates.map((documentTemplate) => (
                  <option key={documentTemplate.id} value={documentTemplate.id}>
                    {documentTemplate.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Protocol number</span>
              <input
                value={form.protocol_number}
                onChange={(event) => setForm((current) => ({ ...current, protocol_number: event.target.value }))}
                required
              />
            </label>
            <label className="field-stack">
              <span className="field-label">Date</span>
              <input
                type="date"
                value={form.protocol_date}
                onChange={(event) => setForm((current) => ({ ...current, protocol_date: event.target.value }))}
                required
              />
            </label>
            <label className="field-stack">
              <span className="field-label">Title</span>
              <input
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                placeholder="Optional title"
              />
            </label>
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
          <button type="button" className={`segment-button${statusFilter === "draft" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("draft")}>Draft</button>
          <button type="button" className={`segment-button${statusFilter === "released" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("released")}>Released</button>
          <button type="button" className={`segment-button${statusFilter === "archived" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("archived")}>Archived</button>
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
              <span className="pill">{documentTemplates.length} layouts</span>
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
              <div className="muted">Protocol #{protocol.id}</div>
            </td>
            <td>
              {protocol.title ?? "Untitled protocol"}
            </td>
            <td><span className={`pill status-pill-${protocol.status}`}>{protocol.status}</span></td>
            <td>
              Template #{protocol.template_id}
              <div className="muted">Layout #{protocol.document_template_id ?? "none"}</div>
            </td>
            <td>{protocol.protocol_date ?? "No date"}</td>
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
  documentTemplates?: DocumentTemplate[];
};

export function ProtocolOverview({ protocol, documentTemplates = [] }: ProtocolOverviewProps) {
  const [selectedDocumentTemplateId, setSelectedDocumentTemplateId] = useState(
    protocol.document_template_id ? String(protocol.document_template_id) : documentTemplates[0] ? String(documentTemplates[0].id) : ""
  );
  const [layoutStatus, setLayoutStatus] = useState("Ready");

  async function saveDocumentTemplate() {
    if (!selectedDocumentTemplateId) {
      return;
    }
    setLayoutStatus("Saving layout...");
    try {
      await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocol.id}`, {
        method: "PATCH",
        body: JSON.stringify({ document_template_id: Number(selectedDocumentTemplateId) })
      });
      setLayoutStatus("Layout updated");
    } catch (error) {
      setLayoutStatus(error instanceof Error ? error.message : "Layout update failed");
    }
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">Status: {protocol.status}</span>
        <span className="pill">Template #{protocol.template_id}</span>
        <span className="pill">Layout #{protocol.document_template_id ?? "none"}</span>
      </div>

      <div className="two-col">
        <article className="card">
          <div className="eyebrow">Overview</div>
          <h3>{protocol.title ?? "Untitled protocol"}</h3>
          <p className="muted">Protocol date: {protocol.protocol_date ?? "unknown"}</p>
          <p className="muted">Template version snapshot: {protocol.template_version ?? "unknown"}</p>
          <p className="muted">Created at: {protocol.created_at ?? "unknown"}</p>
        </article>

        <article className="card">
          <div className="eyebrow">Document Layout</div>
          <h3>Select LaTeX template</h3>
          <p className="muted">Choose which reusable document layout this protocol should use for PDF generation.</p>
          <div className="grid">
            <select value={selectedDocumentTemplateId} onChange={(event) => setSelectedDocumentTemplateId(event.target.value)}>
              {documentTemplates.map((documentTemplate) => (
                <option key={documentTemplate.id} value={documentTemplate.id}>
                  {documentTemplate.name}
                </option>
              ))}
            </select>
            <div className="table-toolbar-actions">
              <button type="button" className="button-inline" onClick={() => void saveDocumentTemplate()}>
                Save layout
              </button>
              <Link href="/protocols">Back to protocol list</Link>
            </div>
            <p className="muted">{layoutStatus}</p>
          </div>
        </article>
      </div>
    </div>
  );
}
