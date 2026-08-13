"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { Menu, MenuItem, Popover } from "@/components/ui/popover";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { usePdfExport, PdfExportResult } from "@/lib/hooks/use-pdf-export";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { ProtocolSummary, TemplateSummary } from "@/types/api";
import { protocolStatusLabel, protocolStatusVariant } from "@/components/protocol/protocol-status";

const PAGE_SIZE = 100;

const STATUS_FILTER_OPTIONS: FilterTabOption[] = [
  { value: "all", label: "Alle" },
  { value: "geplant", label: "Geplant" },
  { value: "vorbereitet", label: "Vorbereitet" },
  { value: "durchgeführt", label: "Durchgeführt" },
  { value: "abgeschlossen", label: "Abgeschlossen" },
];

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
  const confirm = useConfirm();
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [availableTemplates, setAvailableTemplates] = useState(templates);
  const { busyByProtocol: pdfBusyByProtocol, generatePdf, openOrGeneratePdf } = usePdfExport();
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const menuBtnRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const activeMenuAnchorRef = useRef<HTMLButtonElement | null>(null);
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

  const sortedProtocols = useMemo(() => {
    return [...protocols]
      .filter((protocol) => {
        const haystack = `${protocol.protocol_number} ${protocol.title ?? ""}`.toLowerCase();
        const matchesSearch = !search || haystack.includes(search.toLowerCase());
        const matchesStatus = statusFilter === "all" || protocol.status === statusFilter;
        return matchesSearch && matchesStatus;
      })
      .sort((a, b) => (b.protocol_date ?? "").localeCompare(a.protocol_date ?? ""));
  }, [protocols, search, statusFilter]);

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
      showToast(`Protokoll #${created.id} erstellt`, "success");
      setForm((current) => ({
        ...current,
        protocol_number: "",
        title: ""
      }));
      setShowCreateForm(false);
      router.push(`/protocols/${created.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Protokoll konnte nicht erstellt werden", "error");
    }
  }

  async function deleteProtocol(protocolId: number) {
    const ok = await confirm({
      message: "Protokoll endgültig löschen? Dies kann nicht rückgängig gemacht werden.",
      tone: "danger",
      confirmLabel: "Löschen"
    });
    if (!ok) return;
    try {
      await browserApiFetch<{ message: string }>(`/api/protocols/${protocolId}`, { method: "DELETE" });
      setProtocols((current) => current.filter((protocol) => protocol.id !== protocolId));
      showToast(`Protokoll #${protocolId} gelöscht`, "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Protokoll konnte nicht gelöscht werden", "error");
    }
  }

  function handlePdfExported(protocolId: number, result: PdfExportResult) {
    // Update version in local protocol list
    if (result.version_major != null && result.version_minor != null) {
      setProtocols((current) =>
        current.map((p) =>
          p.id === protocolId ? { ...p, version_major: result.version_major!, version_minor: result.version_minor! } : p
        )
      );
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

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

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
      <div className="page-header">
        <div>
          <h1 className="page-title">Protokolle</h1>
          <p className="muted">Alle Sitzungsprotokolle dieses Mandanten.</p>
        </div>
        {!readOnly ? (
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((c) => !c)}>
            {showCreateForm ? "Abbrechen" : "+ Neues Protokoll"}
          </button>
        ) : null}
      </div>

      <div className="list-filter-row">
        <FilterTabs options={STATUS_FILTER_OPTIONS} value={statusFilter} onChange={setStatusFilter} />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Protokolle durchsuchen" />
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

      <article className="card">
        <div className="record-list">
          {sortedProtocols.map((protocol) => {
            const isFinal = protocol.status === "abgeschlossen";
            const menuOpen = openMenuId === protocol.id;
            const statusVariant = protocolStatusVariant(protocol.status);
            const subtitle = [
              protocol.protocol_number,
              formatDate(protocol.protocol_date) || null,
              !readOnly ? templates.find((t) => t.id === protocol.template_id)?.name ?? null : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div key={protocol.id} className="record-list-row" onClick={() => router.push(`/protocols/${protocol.id}`)}>
                <span className={`record-list-row-dot record-list-row-dot-${statusVariant}`} aria-hidden="true" />
                <span className="record-list-row-text">
                  <span className="record-list-row-title">{protocol.title ?? protocol.protocol_number}</span>
                  <span className="record-list-row-sub">{subtitle}</span>
                </span>
                <div className="record-list-row-trailing" onClick={(e) => e.stopPropagation()}>
                  {protocol.import_source_filename && (
                    <span title={`Importiert aus ${protocol.import_source_filename}`}>
                      <Badge variant="info">Importiert</Badge>
                    </span>
                  )}
                  <Badge variant={statusVariant}>{protocolStatusLabel(protocol.status)}</Badge>
                  {isFinal ? (
                    <button
                      type="button"
                      className={`pdf-icon-link pdf-icon-link-success pdf-icon-link-sm${pdfBusyByProtocol[protocol.id] ? " pdf-icon-disabled" : ""}`}
                      onClick={() => openOrGeneratePdf(protocol, (result) => handlePdfExported(protocol.id, result))}
                      aria-label={`PDF exportieren für ${protocol.protocol_number}`}
                      title="PDF exportieren"
                      disabled={pdfBusyByProtocol[protocol.id]}
                    >
                      {pdfBusyByProtocol[protocol.id] ? "..." : "PDF"}
                    </button>
                  ) : (
                    <span className="record-list-row-pdf-spacer" aria-hidden="true" />
                  )}
                  {!readOnly && (
                    <button
                      type="button"
                      className="button-ghost button-icon"
                      title="Weitere Aktionen"
                      ref={(el) => { menuBtnRefs.current[protocol.id] = el; }}
                      onClick={() => {
                        if (menuOpen) {
                          setOpenMenuId(null);
                        } else {
                          activeMenuAnchorRef.current = menuBtnRefs.current[protocol.id] ?? null;
                          setOpenMenuId(protocol.id);
                        }
                      }}
                    >
                      ⋯
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {sortedProtocols.length === 0 ? <p className="muted record-list-empty">Keine Protokolle gefunden.</p> : null}
      </article>

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">Lädt weitere Protokolle…</span>
          ) : (
            <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()}>
              Mehr laden ({protocols.length} geladen)
            </button>
          )}
        </div>
      )}

      {!readOnly && (
        <Popover
          open={openMenuId !== null}
          onOpenChange={(open) => { if (!open) setOpenMenuId(null); }}
          anchorRef={activeMenuAnchorRef}
          align="end"
        >
          <Menu>
            {(() => {
              const protocol = sortedProtocols.find((p) => p.id === openMenuId);
              if (!protocol) return null;
              const canRevert = protocol.status !== "geplant";
              return (
                <>
                  <MenuItem
                    onSelect={() => {
                      setOpenMenuId(null);
                      openOrGeneratePdf(protocol, (result) => handlePdfExported(protocol.id, result));
                    }}
                  >
                    {pdfBusyByProtocol[protocol.id] ? "Generiere…" : "PDF"}
                  </MenuItem>
                  <MenuItem
                    onSelect={() => {
                      setOpenMenuId(null);
                      void generatePdf(protocol.id, protocol.protocol_number, (result) => handlePdfExported(protocol.id, result));
                    }}
                  >
                    {pdfBusyByProtocol[protocol.id] ? "Generiere…" : "PDF neu generieren"}
                  </MenuItem>
                  {canRevert && (
                    <MenuItem
                      onSelect={() => {
                        setOpenMenuId(null);
                        void revertStatus(protocol.id);
                      }}
                    >
                      Status zurücksetzen
                    </MenuItem>
                  )}
                  <MenuItem
                    danger
                    onSelect={() => {
                      setOpenMenuId(null);
                      void deleteProtocol(protocol.id);
                    }}
                  >
                    Löschen
                  </MenuItem>
                </>
              );
            })()}
          </Menu>
        </Popover>
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
        <Badge variant={protocolStatusVariant(protocol.status)}>Status: {protocolStatusLabel(protocol.status)}</Badge>
        <span className="pill">Template zugewiesen</span>
        <span className="pill">Layout aus Vorlagen-Snapshot</span>
      </div>

      <article className="card">
        <div className="eyebrow">Übersicht</div>
        <h3>{protocol.title ?? "Unbenanntes Protokoll"}</h3>
        <p className="muted">Protokolldatum: {formatDate(protocol.protocol_date) || "unbekannt"}</p>
        <p className="muted">Vorlagenversion-Snapshot: {protocol.template_version ?? "unbekannt"}</p>
        <p className="muted">Erstellt am: {formatDateTime(protocol.created_at) || "unbekannt"}</p>
      </article>
    </div>
  );
}
