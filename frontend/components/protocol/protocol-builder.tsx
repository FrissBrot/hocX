"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useRefreshOnRestore } from "@/lib/hooks/use-refresh-on-restore";

import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { usePdfExport, PdfExportResult } from "@/lib/hooks/use-pdf-export";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { ProtocolSummary, TemplateSummary } from "@/types/api";
import { protocolStatusLabel, protocolStatusVariant } from "@/components/protocol/protocol-status";

const PAGE_SIZE = 100;

// Resolves a template pattern ("Sitzung {n} - {date:DD.MM.YYYY}") into a readable preview
// for the create dialog - audit finding F4, 2026-10-01: the raw placeholder syntax was
// shown unlabeled and unresolved, which non-technical users read as a display bug rather
// than a preview. {n} (the server-assigned sequence number) isn't known until creation, so
// it's spelled out instead of faked with a specific number.
function resolvePatternPreview(pattern: string, protocolDateIso: string, t: (key: string) => string): string {
  return pattern.replace(/\{n\}/g, t("builder.sequenceNumberPlaceholder")).replace(/\{date(?::[^}]*)?\}/g, formatDate(protocolDateIso) || t("builder.datePlaceholder"));
}

function statusFilterOptions(t: (key: string) => string): FilterTabOption[] {
  return [
    { value: "all", label: t("builder.filterAll") },
    { value: "geplant", label: t("status.geplant") },
    { value: "vorbereitet", label: t("status.vorbereitet") },
    { value: "durchgeführt", label: t("status.durchgeführt") },
    { value: "abgeschlossen", label: t("status.abgeschlossen") },
  ];
}

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
  const t = useTranslations("protocols.builder");
  const tRoot = useTranslations("protocols");
  const locale = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  useRefreshOnRestore();
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
  const { busyByProtocol: pdfBusyByProtocol, openOrGeneratePdf } = usePdfExport();
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

  useEffect(() => {
    if (readOnly) return;
    if (searchParams.get("create") === "1") {
      setShowCreateForm(true);
      router.replace("/protocols", { scroll: false });
    }
  }, [searchParams, readOnly, router]);

  const hasNoProtocols = protocols.length === 0 && !hasMore;

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
      const created = await browserApiFetch<{ id: string }>("/api/protocols/from-template", {
        method: "POST",
        body: JSON.stringify({
          template_id: form.template_id,
          protocol_number: autoProtocolNumber ? null : form.protocol_number || null,
          protocol_date: form.protocol_date,
          title: autoTitle ? null : form.title || null,
          created_by: null,
          event_id: null
        })
      });

      const full = await browserApiFetch<ProtocolSummary>(`/api/protocols/${created.id}`);
      setProtocols((current) => [full, ...current]);
      showToast(t("created", { name: full.title ?? full.protocol_number }), "success");
      setForm((current) => ({
        ...current,
        protocol_number: "",
        title: ""
      }));
      setShowCreateForm(false);
      router.push(`/protocols/${created.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailed"), "error");
    }
  }

  async function deleteProtocol(protocolId: string) {
    const ok = await confirm({
      message: t("deleteConfirmMessage"),
      tone: "danger",
      confirmLabel: t("delete")
    });
    if (!ok) return;
    try {
      const deletedProtocol = protocols.find((protocol) => protocol.id === protocolId);
      const deletedLabel = deletedProtocol?.title ?? deletedProtocol?.protocol_number ?? t("unnamed");
      await browserApiFetch<{ message: string }>(`/api/protocols/${protocolId}`, { method: "DELETE" });
      setProtocols((current) => current.filter((protocol) => protocol.id !== protocolId));
      showToast(t("deleted", { name: deletedLabel }), "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailed"), "error");
    }
  }

  function handlePdfExported(protocolId: string, result: PdfExportResult) {
    setProtocols((current) =>
      current.map((p) =>
        p.id === protocolId ? {
          ...p,
          latest_pdf_url: result.content_url ?? p.latest_pdf_url,
          version_major: result.version_major ?? p.version_major,
          version_minor: result.version_minor ?? p.version_minor,
        } : p
      )
    );
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

  async function revertStatus(protocolId: string) {
    try {
      const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocolId}/revert-status`, { method: "POST" });
      setProtocols((current) => current.map((p) => (p.id === protocolId ? updated : p)));
      showToast(t("statusChanged", { status: protocolStatusLabel(updated.status, tRoot) }), "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("revertFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        {!readOnly && !hasNoProtocols ? (
          <button type="button" className={showCreateForm ? "button-ghost" : "button-primary"} onClick={() => setShowCreateForm((c) => !c)}>
            {showCreateForm ? t("cancel") : t("newProtocol")}
          </button>
        ) : null}
      </div>

      {hasNoProtocols ? null : (
        <div className="list-filter-row">
          <FilterTabs options={statusFilterOptions(tRoot)} value={statusFilter} onChange={setStatusFilter} />
          <div className="list-filter-search">
            <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
          </div>
        </div>
      )}

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title={t("createTitle")}
        description={t("createDescription")}
      >
        <ModalSaveForm className="grid" onSubmit={createProtocol}>
          <label className="field-stack">
            <span className="field-label">{t("template")}</span>
            <SearchableSelect
              options={availableTemplates}
              getId={(template) => String(template.id)}
              getLabel={(template) => template.name}
              value={form.template_id || null}
              onChange={(template) => setForm((current) => ({ ...current, template_id: template ? String(template.id) : "" }))}
            />
          </label>
          {selectedTemplate?.protocol_number_pattern || selectedTemplate?.title_pattern ? (
            <div className="field-stack">
              <span className="field-label">{t("preview")}</span>
              <div className="info-note">
                {selectedTemplate.protocol_number_pattern
                  ? t("numberPreview", { preview: resolvePatternPreview(selectedTemplate.protocol_number_pattern, form.protocol_date, tRoot) })
                  : t("numberManual")}
                {" · "}
                {selectedTemplate.title_pattern
                  ? t("titlePreview", { preview: resolvePatternPreview(selectedTemplate.title_pattern, form.protocol_date, tRoot) })
                  : t("titleManual")}
              </div>
            </div>
          ) : null}
          <div className="three-col">
            {!autoProtocolNumber ? (
              <label className="field-stack">
                <span className="field-label">{t("number")}</span>
                <input
                  value={form.protocol_number}
                  onChange={(event) => setForm((current) => ({ ...current, protocol_number: event.target.value }))}
                  placeholder={t("numberPlaceholder")}
                />
              </label>
            ) : null}
            <label className="field-stack">
              <span className="field-label">{t("date")}</span>
              <DateInput value={form.protocol_date} onChange={(value) => setForm((current) => ({ ...current, protocol_date: value }))} required />
            </label>
            {!autoTitle ? (
              <label className="field-stack">
                <span className="field-label">{t("protocolTitle")}</span>
                <input
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                  placeholder={t("titlePlaceholder")}
                />
              </label>
            ) : null}
          </div>
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary" disabled={!form.template_id}>
              {t("create")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      {hasNoProtocols ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            readOnly ? null : (
              <>
                <button type="button" className="button-primary" onClick={() => setShowCreateForm(true)}>
                  {t("newProtocol")}
                </button>
                <button type="button" className="button-secondary" onClick={() => router.push("/tools/word-import")}>
                  {t("importWord")}
                </button>
              </>
            )
          }
          hint={t("emptyHint")}
        />
      ) : (
      <article className="card">
        <div className="record-list">
          {sortedProtocols.map((protocol) => {
            const isFinal = protocol.status === "abgeschlossen";
            const previousStatus = ({
              vorbereitet: "geplant",
              durchgeführt: "vorbereitet",
              abgeschlossen: "durchgeführt",
            } as Record<string, string>)[protocol.status];
            const pdfLabel = t("openPdf");
            const actions: ActionMenuItem[] = [];
            if (!isFinal && !pdfBusyByProtocol[protocol.id]) {
              actions.push({
                label: pdfLabel,
                onClick: () => void openOrGeneratePdf(protocol, (result) => handlePdfExported(protocol.id, result)),
              });
            }
            if (previousStatus) {
              actions.push({
                label: t("revertTo", { status: protocolStatusLabel(previousStatus, tRoot) }),
                onClick: () => void revertStatus(protocol.id),
              });
            }
            actions.push({
              label: t("deleteProtocol"),
              danger: true,
              onClick: () => void deleteProtocol(protocol.id),
            });
            const statusVariant = protocolStatusVariant(protocol.status);
            const subtitle = [
              protocol.protocol_number,
              formatDate(protocol.protocol_date) || null,
              !readOnly ? templates.find((candidate) => candidate.id === protocol.template_id)?.name ?? null : null,
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
                    <span title={t("importedFrom", { filename: protocol.import_source_filename })}>
                      <Badge variant="info">{t("imported")}</Badge>
                    </span>
                  )}
                  <Badge variant={statusVariant}>{protocolStatusLabel(protocol.status, tRoot)}</Badge>
                  {isFinal ? (
                    <button
                      type="button"
                      className={`pdf-icon-link pdf-icon-link-success pdf-icon-link-sm${pdfBusyByProtocol[protocol.id] ? " pdf-icon-disabled" : ""}`}
                      onClick={() => openOrGeneratePdf(protocol, (result) => handlePdfExported(protocol.id, result))}
                      aria-label={t("openPdfFor", { number: protocol.protocol_number })}
                      title={pdfLabel}
                      disabled={pdfBusyByProtocol[protocol.id]}
                    >
                      {pdfBusyByProtocol[protocol.id] ? "..." : "PDF"}
                    </button>
                  ) : (
                    <span className="record-list-row-pdf-spacer" aria-hidden="true" />
                  )}
                  {!readOnly && (
                    <ActionMenu items={actions} ariaLabel={t("actionsFor", { number: protocol.protocol_number })} />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {sortedProtocols.length === 0 ? <p className="muted record-list-empty">{t("noProtocolsFound")}</p> : null}
      </article>
      )}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("loadingMore")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("loadMore", { count: protocols.length })}
            </button>
          )}
        </div>
      )}

    </div>
  );
}

type ProtocolOverviewProps = {
  protocol: ProtocolSummary;
};

export function ProtocolOverview({ protocol }: ProtocolOverviewProps) {
  const t = useTranslations("protocols.overview");
  const tRoot = useTranslations("protocols");
  const locale = useLocale();
  const unknown = t("unknown");
  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <Badge variant={protocolStatusVariant(protocol.status)}>{t("status", { status: protocolStatusLabel(protocol.status, tRoot) })}</Badge>
        <span className="pill">{t("templateAssigned")}</span>
        <span className="pill">{t("layoutFromSnapshot")}</span>
      </div>

      <article className="card">
        <div className="eyebrow">{t("overview")}</div>
        <h3>{protocol.title ?? t("unnamedProtocol")}</h3>
        <p className="muted">{t("protocolDate", { date: formatDate(protocol.protocol_date) || unknown })}</p>
        <p className="muted">{t("templateVersionSnapshot", { version: protocol.template_version ?? unknown })}</p>
        <p className="muted">{t("createdAt", { date: formatDateTime(protocol.created_at, locale) || unknown })}</p>
      </article>
    </div>
  );
}
