"use client";

import { ReactNode, useState, useSyncExternalStore } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DocumentExportDialog } from "@/components/documents/export-dialog";
import { ActionIcon } from "@/components/ui/action-icons";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { HelpPopover } from "@/components/ui/help-popover";
import { Modal } from "@/components/ui/modal";
import { Switch } from "@/components/ui/switch";
import { docsUrl } from "@/lib/docs";
import { useShortcutLabel } from "@/lib/search/shortcuts";
import { formatDateTime } from "@/lib/utils/format";

// Kopf des Protokoll-Editors (Design «Protokoll-Header», Variante «Mit Workflow-Leiste»):
// oben Zurück, Titel, Meta-Zeile und Aktionen (Suche, Export, «⋯»), darunter die Workflow-Leiste
// mit den vier Schritten (nur Anzeige), dem Hinweis «Vorlage geändert», dem Schalter
// «Nachverfolgen» und dem Hauptknopf. Alle Aktionen kommen unverändert aus dem Editor.

export const PROTOCOL_WORKFLOW_STEPS = ["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"] as const;

const STEP_LABEL_KEYS: Record<(typeof PROTOCOL_WORKFLOW_STEPS)[number], string> = {
  geplant: "header.stepPlanned",
  vorbereitet: "header.stepSession",
  durchgeführt: "header.stepPostProcessing",
  abgeschlossen: "header.stepDone",
};

const noSubscribe = () => () => {};

type Props = {
  title: string;
  protocolNumber: string;
  createdAt?: string | null;
  templateVersion?: number | null;
  status: string;
  /** Kein Hauptknopf und kein Schalter (abgeschlossen oder nur lesend) */
  isReadOnly: boolean;
  ctaLabel?: string;
  ctaBusy: boolean;
  onCta: () => void;
  trackChanges: { visible: boolean; enabled: boolean; onChange: (enabled: boolean) => void };
  templateChange: { visible: boolean; busy: boolean; onReload: () => void };
  importSource?: { url: string; filename?: string | null } | null;
  onOpenSearch: () => void;
  pdf: { busy: boolean; onOpen: () => void };
  protocolId: string;
  presence: ReactNode;
};

export function ProtocolHeader({
  title,
  protocolNumber,
  createdAt,
  templateVersion,
  status,
  isReadOnly,
  ctaLabel,
  ctaBusy,
  onCta,
  trackChanges,
  templateChange,
  importSource,
  onOpenSearch,
  pdf,
  protocolId,
  presence,
}: Props) {
  const t = useTranslations("protocols.editor");
  const tHelp = useTranslations("common.help");
  const locale = useLocale();
  const shortcut = useShortcutLabel();
  const [exportOpen, setExportOpen] = useState(false);
  const [workflowHelpOpen, setWorkflowHelpOpen] = useState(false);
  // Doku-Adresse erst nach der Hydration (wie HelpPopover)
  const workflowDocsHref = useSyncExternalStore(noSubscribe, () => docsUrl("protokolle", "status"), () => null);

  const currentIndex = PROTOCOL_WORKFLOW_STEPS.indexOf(status as (typeof PROTOCOL_WORKFLOW_STEPS)[number]);
  const finished = status === "abgeschlossen";

  const exportItems: ActionMenuItem[] = [
    { label: pdf.busy ? t("header.pdfBusy") : t("header.openPdf"), onClick: pdf.onOpen, disabled: pdf.busy },
    { label: t("header.exportDialog"), onClick: () => setExportOpen(true) },
  ];
  const moreItems: ActionMenuItem[] = [
    ...(importSource
      ? [{ label: t("openOriginalDocument"), onClick: () => { window.location.href = importSource.url; } }]
      : []),
    { label: t("header.workflowHelpItem"), onClick: () => setWorkflowHelpOpen(true) },
  ];

  return (
    <header className="protocol-header">
      <div className="protocol-header-top">
        <a href="/protocols" className="button-ghost button-icon protocol-header-back" aria-label={t("header.back")} title={t("header.back")}>
          <span aria-hidden="true">←</span>
        </a>
        <div className="protocol-header-heading">
          <h1 className="protocol-header-title">{title}</h1>
          <p className="protocol-header-meta">
            <span className="protocol-header-number">{protocolNumber}</span>
            {createdAt ? (
              <>
                <span className="protocol-header-meta-sep" aria-hidden="true">·</span>
                <span>{t("header.created", { date: formatDateTime(createdAt, locale) })}</span>
              </>
            ) : null}
            {templateVersion != null ? (
              <>
                <span className="protocol-header-meta-sep" aria-hidden="true">·</span>
                <span title={t("templateVersionPill", { version: templateVersion })}>{t("header.templateVersion", { version: templateVersion })}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="protocol-header-actions">
          <div className="protocol-header-presence">{presence}</div>
          <button
            type="button"
            className="protocol-header-search"
            onClick={onOpenSearch}
            aria-label={t("header.searchAria", { shortcut: shortcut("F") })}
          >
            <svg className="protocol-header-search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="5.25" stroke="currentColor" strokeWidth="1.5" />
              <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span className="protocol-header-search-label" aria-hidden="true">{t("header.searchLabel")}</span>
            <kbd className="protocol-header-kbd" aria-hidden="true">{t("ctrlFHint", { shortcut: shortcut("F") })}</kbd>
          </button>
          <ActionMenu
            ariaLabel={t("header.exportMenu")}
            icon={<ActionIcon name="download" />}
            triggerClassName="button-ghost button-icon protocol-header-icon"
            items={exportItems}
          />
          <ActionMenu
            ariaLabel={t("header.moreMenu")}
            icon="⋯"
            triggerClassName="button-ghost button-icon protocol-header-icon"
            items={moreItems}
          />
        </div>
      </div>

      <div className="protocol-workflow">
        <ol className="protocol-workflow-steps" aria-label={t("header.workflowLabel")}>
          {PROTOCOL_WORKFLOW_STEPS.map((step, index) => {
            const isCurrent = index === currentIndex;
            const isDone = index < currentIndex || (finished && isCurrent);
            return (
              <li
                key={step}
                className={`protocol-workflow-step${isCurrent ? " protocol-workflow-step-current" : ""}${isDone ? " protocol-workflow-step-done" : ""}`}
                aria-current={isCurrent ? "step" : undefined}
              >
                <span className="protocol-workflow-step-marker" aria-hidden="true">{isDone ? "✓" : index + 1}</span>
                <span className="protocol-workflow-step-label">{t(STEP_LABEL_KEYS[step])}</span>
                {isDone ? <span className="visually-hidden">{t("header.stepDoneHint")}</span> : null}
              </li>
            );
          })}
        </ol>

        {templateChange.visible ? (
          <div className="protocol-workflow-notice">
            <Badge variant="warning" dot>{t("templateChangedHint")}</Badge>
            <button type="button" className="button-secondary button-ghost" disabled={templateChange.busy} onClick={templateChange.onReload}>
              {t("header.templateReload")}
            </button>
          </div>
        ) : null}

        {!isReadOnly && (trackChanges.visible || ctaLabel) ? (
          <div className="protocol-workflow-actions">
            {trackChanges.visible ? (
              <div className="protocol-workflow-track">
                <Switch
                  className="protocol-workflow-switch"
                  checked={trackChanges.enabled}
                  onChange={trackChanges.onChange}
                  label={t("header.trackChanges")}
                />
                <HelpPopover topic={t("trackChangesHelpTopic")} docs={{ page: "protokolle", anchor: "nachverfolgen" }}>
                  {t("trackChangesHelp")}
                </HelpPopover>
              </div>
            ) : null}
            {ctaLabel ? (
              <button type="button" className="button-primary protocol-workflow-cta" disabled={ctaBusy} onClick={onCta}>
                {ctaBusy ? "…" : ctaLabel}
                {ctaBusy ? null : <span aria-hidden="true">→</span>}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {exportOpen ? (
        <DocumentExportDialog open={exportOpen} onClose={() => setExportOpen(false)} context={{ documentType: "protocol", protocolId }} />
      ) : null}
      <Modal open={workflowHelpOpen} title={t("workflowHelpTopic")} onClose={() => setWorkflowHelpOpen(false)}>
        <p className="protocol-workflow-help-text">{t("workflowHelp")}</p>
        {workflowDocsHref ? (
          <a className="help-popover-link" href={workflowDocsHref} target="_blank" rel="noopener noreferrer">
            {tHelp("moreInDocs")}
          </a>
        ) : null}
      </Modal>
    </header>
  );
}
