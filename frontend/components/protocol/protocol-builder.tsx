"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
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

export function ProtocolBuilder({ initialProtocols, templates }: ProtocolBuilderProps) {
  const router = useRouter();
  const [protocols, setProtocols] = useState(initialProtocols);
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

  return (
    <div className="grid">
      <DataToolbar
        title="Protocols"
        description="Create protocol snapshots from templates and open them from the table."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((current) => !current)}>
            {showCreateForm ? "Close create form" : "New protocol"}
          </button>
        }
      />

      {showCreateForm ? (
        <article className="card">
          <div className="eyebrow">Create Protocol</div>
          <form className="grid" onSubmit={createProtocol}>
            <div className="two-col">
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
              <input
                placeholder="Protocol number"
                value={form.protocol_number}
                onChange={(event) => setForm((current) => ({ ...current, protocol_number: event.target.value }))}
                required
              />
            </div>
            <div className="two-col">
              <input
                type="date"
                value={form.protocol_date}
                onChange={(event) => setForm((current) => ({ ...current, protocol_date: event.target.value }))}
                required
              />
              <input
                placeholder="Optional title"
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              />
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline" disabled={!form.template_id}>
                Create protocol
              </button>
            </div>
          </form>
        </article>
      ) : null}

      <article className="card">
        <div className="eyebrow">Filter</div>
        <div className="two-col">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by number or title" />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="released">Released</option>
            <option value="archived">Archived</option>
          </select>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Protocol", "Title", "Template", "Date", "Actions"]}>
        {sortedProtocols.map((protocol) => (
          <tr key={protocol.id} className="table-row-clickable" onClick={() => router.push(`/protocols/${protocol.id}`)}>
            <td>
              <strong>{protocol.protocol_number}</strong>
              <div className="muted">Protocol #{protocol.id}</div>
            </td>
            <td>{protocol.title ?? "Untitled protocol"}</td>
            <td>
              Template #{protocol.template_id}
              <div className="muted">{protocol.status}</div>
            </td>
            <td>{protocol.protocol_date ?? "No date"}</td>
            <td>
              <div className="table-actions">
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
        <span className="pill">Status: {protocol.status}</span>
        <span className="pill">Template #{protocol.template_id}</span>
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
          <div className="eyebrow">Navigation</div>
          <h3>Open related protocol work</h3>
          <p className="muted">
            The table below jumps into block editing, and export actions stay available on the same page.
          </p>
          <Link href="/protocols">Back to protocol list</Link>
        </article>
      </div>
    </div>
  );
}
