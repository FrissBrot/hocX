"use client";

import { memo, ReactNode, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { DocumentExportDialog } from "@/components/documents/export-dialog";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { HelpPopover } from "@/components/ui/help-popover";
import { Modal } from "@/components/ui/modal";
import { Switch } from "@/components/ui/switch";
import { docsUrl } from "@/lib/docs";
import { useModifierLabel, useShortcutLabel } from "@/lib/search/shortcuts";
import { formatDate } from "@/lib/utils/format";

// Kopf des Protokoll-Editors (Design «hocX Protokoll-Editor 1a»): oben Zurück, Status, Titel,
// Speicherstatus, Anwesende, Suche, Export und Hauptknopf; darunter Nummer, Modus, Metadaten,
// Hinweis «Vorlage geändert», Schalter «Nachverfolgen» und rechts die vier Schritte (nur Anzeige).
// Memoisiert mit einfachen Props: der Kopf rendert beim Tippen nicht neu (S5).

export const PROTOCOL_WORKFLOW_STEPS = ["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"] as const;

const STEP_LABEL_KEYS: Record<(typeof PROTOCOL_WORKFLOW_STEPS)[number], string> = {
  geplant: "header.stepPlanned",
  vorbereitet: "header.stepSession",
  durchgeführt: "header.stepPostProcessing",
  abgeschlossen: "header.stepDone",
};

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  geplant: "neutral",
  vorbereitet: "info",
  durchgeführt: "warning",
  abgeschlossen: "success",
};

/** Speicherstatus im Kopf: vier Zustände (F8) plus «noch nichts gespeichert». */
export type ProtocolSaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "offline"; pending: number }
  | { kind: "error" };

const noSubscribe = () => () => {};

type Props = {
  title: string;
  protocolNumber: string;
  createdAt?: string | null;
  templateVersion?: number | null;
  status: string;
  statusLabel: string;
  modeLabel: string;
  /** Kein Hauptknopf und kein Schalter (abgeschlossen oder nur lesend) */
  isReadOnly: boolean;
  ctaLabel?: string;
  ctaBusy: boolean;
  onCta: () => void;
  trackChangesVisible: boolean;
  trackChangesEnabled: boolean;
  onTrackChangesChange: (enabled: boolean) => void;
  templateChangeVisible: boolean;
  templateChangeBusy: boolean;
  onTemplateReload: () => void;
  importSourceUrl?: string | null;
  onOpenSearch: () => void;
  pdfBusy: boolean;
  onOpenPdf: () => void;
  protocolId: string;
  presence: ReactNode;
  saveState: ProtocolSaveState;
  /** Bei «Fehler»: springt zum betroffenen Block */
  onShowSaveError: () => void;
  /** Schmale Fenster (Tablet): Gliederung ein-/ausblenden */
  outlineToggle?: ReactNode;
};

export const ProtocolHeader = memo(function ProtocolHeader({
  title,
  protocolNumber,
  createdAt,
  templateVersion,
  status,
  statusLabel,
  modeLabel,
  isReadOnly,
  ctaLabel,
  ctaBusy,
  onCta,
  trackChangesVisible,
  trackChangesEnabled,
  onTrackChangesChange,
  templateChangeVisible,
  templateChangeBusy,
  onTemplateReload,
  importSourceUrl,
  onOpenSearch,
  pdfBusy,
  onOpenPdf,
  protocolId,
  presence,
  saveState,
  onShowSaveError,
  outlineToggle,
}: Props) {
  const t = useTranslations("protocols.editor");
  const tHelp = useTranslations("common.help");
  const shortcut = useShortcutLabel();
  const modifier = useModifierLabel();
  const [exportOpen, setExportOpen] = useState(false);
  const [workflowHelpOpen, setWorkflowHelpOpen] = useState(false);
  // Doku-Adresse erst nach der Hydration (wie HelpPopover)
  const workflowDocsHref = useSyncExternalStore(noSubscribe, () => docsUrl("protokolle", "status"), () => null);

  const currentIndex = PROTOCOL_WORKFLOW_STEPS.indexOf(status as (typeof PROTOCOL_WORKFLOW_STEPS)[number]);
  const finished = status === "abgeschlossen";

  const exportItems: ActionMenuItem[] = [
    { label: pdfBusy ? t("header.pdfBusy") : t("header.openPdf"), onClick: onOpenPdf, disabled: pdfBusy },
    { label: t("header.exportDialog"), onClick: () => setExportOpen(true) },
  ];
  const moreItems: ActionMenuItem[] = [
    ...(importSourceUrl
      ? [{ label: t("openOriginalDocument"), onClick: () => { window.location.href = importSourceUrl; } }]
      : []),
    { label: t("header.workflowHelpItem"), onClick: () => setWorkflowHelpOpen(true) },
  ];

  return (
    <header className="protocol-header">
      <div className="protocol-header-top">
        <a href="/protocols" className="protocol-header-back" aria-label={t("header.back")}>
          <span aria-hidden="true">←</span> {t("header.backShort")}
        </a>
        <span className="protocol-header-divider" aria-hidden="true" />
        <Badge variant={STATUS_VARIANT[status] ?? "neutral"} dot>{statusLabel}</Badge>
        <h1 className="protocol-header-title">{title}</h1>
        <SaveStateIndicator state={saveState} onShowError={onShowSaveError} />
        <span className="protocol-header-spacer" aria-hidden="true" />
        <div className="protocol-header-presence">{presence}</div>
        <button
          type="button"
          className="button-secondary protocol-header-search"
          onClick={onOpenSearch}
          aria-label={t("header.searchAria", { shortcut: shortcut("F") })}
        >
          <span aria-hidden="true">{t("header.searchShort")}</span>
          <span className="protocol-header-kbds" aria-hidden="true">
            <kbd className="protocol-header-kbd">{modifier}</kbd>
            <kbd className="protocol-header-kbd">F</kbd>{/* i18n-ok: Tastenname */}
          </span>
        </button>
        <ActionMenu
          ariaLabel={t("header.exportMenu")}
          icon={t("header.exportMenu")}
          triggerClassName="button-secondary protocol-header-export"
          items={exportItems}
        />
        <ActionMenu
          ariaLabel={t("header.moreMenu")}
          icon="⋯"
          triggerClassName="button-secondary button-icon protocol-header-icon"
          items={moreItems}
        />
        {!isReadOnly && ctaLabel ? (
          <button type="button" className="button-primary protocol-header-cta" disabled={ctaBusy} onClick={onCta}>
            {ctaBusy ? "…" : ctaLabel}
          </button>
        ) : null}
      </div>

      <div className="protocol-header-meta">
        {outlineToggle}
        <span className="protocol-header-chip protocol-header-number">{protocolNumber}</span>
        <span className="protocol-header-chip">{modeLabel}</span>
        {createdAt ? <span className="protocol-header-chip protocol-header-chip-muted">{t("header.created", { date: formatDate(createdAt) })}</span> : null}
        {templateVersion != null ? (
          <span className="protocol-header-chip protocol-header-chip-muted" title={t("templateVersionPill", { version: templateVersion })}>
            {t("header.templateVersion", { version: templateVersion })}
          </span>
        ) : null}
        {templateChangeVisible ? (
          <span className="protocol-header-notice">
            <Badge variant="warning" dot>{t("templateChangedHint")}</Badge>
            <button type="button" className="button-secondary button-ghost" disabled={templateChangeBusy} onClick={onTemplateReload}>
              {t("header.templateReload")}
            </button>
          </span>
        ) : null}
        {!isReadOnly && trackChangesVisible ? (
          <span className="protocol-header-track">
            <Switch className="protocol-header-switch" checked={trackChangesEnabled} onChange={onTrackChangesChange} label={t("header.trackChanges")} />
            <HelpPopover topic={t("trackChangesHelpTopic")} docs={{ page: "protokolle", anchor: "nachverfolgen" }}>
              {t("trackChangesHelp")}
            </HelpPopover>
          </span>
        ) : null}
        <span className="protocol-header-spacer" aria-hidden="true" />
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
});

/** Speicherstatus (F8): speichert / gespeichert / offline mit wartenden Änderungen / Fehler. */
function SaveStateIndicator({ state, onShowError }: { state: ProtocolSaveState; onShowError: () => void }) {
  const t = useTranslations("protocols.editor.saveState");
  if (state.kind === "error") {
    return (
      <button type="button" className="protocol-save-state protocol-save-state-error" onClick={onShowError}>
        {t("error")}
      </button>
    );
  }
  const label =
    state.kind === "saving" ? t("saving")
      : state.kind === "saved" ? t("saved")
        : state.kind === "offline" ? t("offline", { count: state.pending })
          : "";
  return (
    <span className={`protocol-save-state protocol-save-state-${state.kind}`} role="status" aria-live="polite">
      {label}
    </span>
  );
}
