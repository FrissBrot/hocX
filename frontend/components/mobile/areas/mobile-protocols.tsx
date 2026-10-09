"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { FormEvent, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useAllPages } from "@/components/mobile/mobile-data";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import { MobileActionSheet, MobileChip, MobileChipRow, MobileEmpty, MobileFab, MobileSubHeader } from "@/components/mobile/mobile-ui";
import { dateParts, todayIso } from "@/components/mobile/mobile-utils";
import { groupProtocolsByCycle, visibleCycleGroupCount } from "@/components/protocol/protocol-cycle-groups";
import { protocolStatusLabel } from "@/components/protocol/protocol-status";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { usePdfExport } from "@/lib/hooks/use-pdf-export";
import type { ProtocolListCycle, ProtocolSummary, TemplateSummary } from "@/types/api";

const STATUSES = ["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"] as const;
const PREVIOUS_STATUS: Record<string, string> = { vorbereitet: "geplant", durchgeführt: "vorbereitet", abgeschlossen: "durchgeführt" };

export function MobileProtocols({ initialProtocols, templates, readOnly }: { initialProtocols: ProtocolSummary[]; templates: TemplateSummary[]; readOnly: boolean }) {
  const t = useTranslations("protocols.builder");
  const tRoot = useTranslations("protocols");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const router = useRouter();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const { openOrGeneratePdf } = usePdfExport();
  const [protocols, setProtocols] = useAllPages<ProtocolSummary>("/api/protocols", initialProtocols);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [showOlder, setShowOlder] = useState(false);
  const [actionsFor, setActionsFor] = useState<ProtocolSummary | null>(null);
  const [creating, setCreating] = useState(false);

  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = protocols.filter(
      (protocol) =>
        (!status || protocol.status === status) &&
        (!needle || `${protocol.protocol_number} ${protocol.title ?? ""}`.toLowerCase().includes(needle))
    );
    return groupProtocolsByCycle(filtered);
  }, [protocols, search, status]);
  const filtering = !!search.trim() || !!status;
  const visibleCount = showOlder || filtering ? groups.length : visibleCycleGroupCount(groups);

  function cycleLabel(cycle: ProtocolListCycle | null): string {
    if (!cycle) return t("noCycle");
    const name = cycle.name ?? t("calendarYear", { year: cycle.cycle_year });
    return cycle.is_current ? `${t("currentCycle")} · ${name}` : name;
  }

  async function remove(protocol: ProtocolSummary) {
    if (!(await confirm({ message: t("deleteConfirmMessage"), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}`, { method: "DELETE" });
      setProtocols((list) => list.filter((item) => item.id !== protocol.id));
      showToast(t("deleted", { name: protocol.title ?? protocol.protocol_number }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailed"), "error");
    }
  }

  async function revert(protocol: ProtocolSummary) {
    try {
      const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocol.id}/revert-status`, { method: "POST" });
      setProtocols((list) => list.map((item) => (item.id === protocol.id ? { ...updated, cycle: item.cycle } : item)));
      showToast(t("statusChanged", { status: protocolStatusLabel(updated.status, tRoot) }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("revertFailed"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("title")} subtitle={t("description")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
      </div>
      <MobileChipRow>
        <MobileChip active={!status} onClick={() => setStatus(null)}>
          {t("filterAll")}
        </MobileChip>
        {STATUSES.map((value) => (
          <MobileChip key={value} active={status === value} onClick={() => setStatus(status === value ? null : value)}>
            {protocolStatusLabel(value, tRoot)}
          </MobileChip>
        ))}
      </MobileChipRow>

      {groups.slice(0, visibleCount).map((group) => (
        <section key={group.key} className="mobile-list-group">
          <div className="mobile-list-group-header">
            <span className="mobile-list-group-label mobile-list-group-label-muted">{cycleLabel(group.cycle)}</span>
            <span className="mobile-muted-sm">{t("protocolCount", { count: group.protocols.length })}</span>
          </div>
          <div className="mobile-card mobile-list-card">
            {group.protocols.map((protocol) => (
              <div key={protocol.id} className="mobile-list-row">
                <button type="button" className="mobile-row-button" onClick={() => router.push(`/protocols/${protocol.id}` as Route)}>
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{protocol.title ?? protocol.protocol_number}</span>
                    <span className="mobile-row-meta">
                      {[protocol.protocol_date ? dateParts.weekdayDayMonth(protocol.protocol_date, locale) : null, protocol.protocol_number]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="mobile-row-pills">
                      <span className={`mobile-editor-status mobile-editor-status-${STATUSES.indexOf(protocol.status as (typeof STATUSES)[number])}`}>
                        {protocolStatusLabel(protocol.status, tRoot)}
                      </span>
                      {protocol.import_source_filename ? <span className="mobile-status-pill">{t("imported")}</span> : null}
                    </span>
                  </span>
                </button>
                {!readOnly || protocol.status === "abgeschlossen" ? (
                  <button type="button" className="mobile-icon-button" aria-label={t("actionsFor", { number: protocol.protocol_number })} onClick={() => setActionsFor(protocol)}>
                    <MobileIcon name="more" />
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ))}
      {groups.length > visibleCount ? (
        <div className="mobile-section">
          <button type="button" className="button-secondary mobile-button-block" onClick={() => setShowOlder(true)}>
            {t("showOlderCycles", { count: groups.length - visibleCount })}
          </button>
        </div>
      ) : null}
      {groups.length === 0 ? <MobileEmpty title={protocols.length ? t("noProtocolsFound") : t("emptyTitle")} hint={protocols.length ? undefined : t("emptyHint")} /> : null}

      {!readOnly ? <MobileFab label={tMobile("protocols.fab")} onClick={() => setCreating(true)} /> : null}

      {actionsFor ? (
        <MobileActionSheet
          title={`${actionsFor.title ?? actionsFor.protocol_number} · ${actionsFor.protocol_number}`}
          onClose={() => setActionsFor(null)}
          actions={[
            { label: t("openPdf"), onClick: () => void openOrGeneratePdf(actionsFor) },
            ...(!readOnly && PREVIOUS_STATUS[actionsFor.status]
              ? [{ label: t("revertTo", { status: protocolStatusLabel(PREVIOUS_STATUS[actionsFor.status], tRoot) }), onClick: () => void revert(actionsFor) }]
              : []),
            ...(!readOnly ? [{ label: t("deleteProtocol"), danger: true, onClick: () => void remove(actionsFor) }] : []),
          ]}
        />
      ) : null}
      {creating ? <CreateProtocolSheet templates={templates} onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

function CreateProtocolSheet({ templates, onClose }: { templates: TemplateSummary[]; onClose: () => void }) {
  const t = useTranslations("protocols.builder");
  const tMobile = useTranslations("mobile");
  const router = useRouter();
  const showToast = useToast();
  const [templateId, setTemplateId] = useState(templates[0]?.id ?? "");
  const [date, setDate] = useState(todayIso());
  const [number, setNumber] = useState("");
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const template = templates.find((item) => item.id === templateId) ?? null;
  const numberPattern = template?.protocol_number_pattern?.trim() || null;
  const titlePattern = template?.title_pattern?.trim() || null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!templateId || !date || saving) return;
    setSaving(true);
    try {
      const created = await browserApiFetch<{ id: string }>("/api/protocols/from-template", {
        method: "POST",
        body: JSON.stringify({
          template_id: templateId,
          protocol_number: numberPattern ? null : number || null,
          protocol_date: date,
          title: titlePattern ? null : title || null,
          created_by: null,
          event_id: null,
        }),
      });
      onClose();
      router.push(`/protocols/${created.id}` as Route);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open size="sheet" title={t("createTitle")} description={t("createDescription")} onClose={onClose} className="mobile-sheet">
      <form className="grid mobile-sheet-body" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">{t("template")}</span>
          <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
            {templates.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("date")}</span>
          <DateInput value={date} onChange={setDate} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("number")}</span>
          {numberPattern ? (
            <span className="mobile-muted-sm">{t("numberPreview", { preview: numberPattern })}</span>
          ) : (
            <input value={number} onChange={(event) => setNumber(event.target.value)} placeholder={t("numberPlaceholder")} />
          )}
        </label>
        <label className="field-stack">
          <span className="field-label">{t("protocolTitle")}</span>
          {titlePattern ? (
            <span className="mobile-muted-sm">{t("titlePreview", { preview: titlePattern })}</span>
          ) : (
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t("titlePlaceholder")} />
          )}
        </label>
        <p className="mobile-desktop-hint-text">{tMobile("protocols.wordImportHint")}</p>
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="submit" className="button-primary" data-modal-save disabled={!templateId || !date || saving}>
            {t("create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
