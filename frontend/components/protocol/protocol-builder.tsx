"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";

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
  const [protocols, setProtocols] = useState(initialProtocols);
  const [status, setStatus] = useState("Ready");
  const [form, setForm] = useState<ProtocolFormState>({
    template_id: templates[0] ? String(templates[0].id) : "",
    protocol_number: "",
    protocol_date: new Date().toISOString().slice(0, 10),
    title: ""
  });

  const sortedProtocols = useMemo(
    () => [...protocols].sort((left, right) => right.id - left.id),
    [protocols]
  );

  async function createProtocol(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating protocol...");

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
      setForm((current) => ({
        ...current,
        protocol_number: "",
        title: ""
      }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Protocol creation failed");
    }
  }

  return (
    <div className="grid">
      <article className="card">
        <div className="eyebrow">Create Protocol</div>
        <h3>Create from template snapshot</h3>
        <form className="grid" onSubmit={createProtocol}>
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
          <button type="submit" disabled={!form.template_id}>
            Create protocol from template
          </button>
        </form>
        <p className="muted">{status}</p>
      </article>

      <article className="card">
        <div className="eyebrow">Snapshot Rule</div>
        <h3>Protocols freeze template structure</h3>
        <p className="muted">
          Creation calls the backend snapshot function so later template changes do not mutate older protocols.
        </p>
      </article>

      <div className="grid">
        {sortedProtocols.map((protocol) => (
          <article className="card" key={protocol.id}>
            <div className="eyebrow">{protocol.protocol_number}</div>
            <h3>{protocol.title ?? "Untitled protocol"}</h3>
            <p className="muted">
              Template #{protocol.template_id} · {protocol.status}
            </p>
            <p className="muted">{protocol.protocol_date ?? "No protocol date"}</p>
            <Link href={`/protocols/${protocol.id}`}>Open protocol detail</Link>
          </article>
        ))}
        {sortedProtocols.length === 0 ? (
          <article className="card">
            <h3>No protocols yet</h3>
            <p className="muted">Create the first protocol from one of your templates above.</p>
          </article>
        ) : null}
      </div>
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
          <div className="eyebrow">Next Step</div>
          <h3>Protocol editor follows in step 6</h3>
          <p className="muted">
            This detail page already loads real protocol metadata. The block editor and autosave will attach here next.
          </p>
          <Link href="/protocols">Back to protocol list</Link>
        </article>
      </div>
    </div>
  );
}
