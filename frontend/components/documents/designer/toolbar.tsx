"use client";

// Obere Werkzeugleiste: Vorlagenname, Speicherstatus, Rückgängig/Wiederholen, Modus, Ansicht
// (Gestalten/Vorschau/Geteilt), Seitenformat, Zoom, Status und Veröffentlichen.

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import type { EditorMode, PageSetup } from "@/components/documents/designer/toolbar-types";

export type SaveState = "saved" | "dirty" | "saving" | "conflict" | "error";
export type ViewMode = "design" | "split" | "preview";

type Props = {
  name: string;
  onRename: (name: string) => void;
  editable: boolean;
  saveState: SaveState;
  onSave: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  view: ViewMode;
  onViewChange: (view: ViewMode) => void;
  page: PageSetup;
  onPageSize: (size: PageSetup["size"]) => void;
  onOrientation: (orientation: PageSetup["orientation"]) => void;
  zoom: number;
  onZoom: (zoom: number) => void;
  status: "draft" | "published" | "unpublished";
  canPublish: boolean;
  onPublish: () => void;
  onDiscard: (() => void) | null;
  // Fehlt im Vorlagen-Editor (eingebetteter Designer)
  onBack?: () => void;
  errorCount: number;
};

export function Toolbar(props: Props) {
  const t = useTranslations("documentStudio");
  const { editable } = props;
  return (
    <header className="studio-toolbar" aria-label={t("toolbar.title")}>
      <div className="studio-toolbar-group">
        {props.onBack ? (
          <button type="button" className="button-ghost" onClick={props.onBack}>
            {t("toolbar.back")}
          </button>
        ) : null}
        <input className="studio-toolbar-name" value={props.name} maxLength={160} aria-label={t("toolbar.name")} disabled={!editable} onChange={(event) => props.onRename(event.target.value)} />
        <span className="studio-save-state" aria-live="polite">
          {t(`toolbar.saveState.${props.saveState}`)}
        </span>
        {props.status === "draft" && <Badge variant="warning">{t("toolbar.statusDraft")}</Badge>}
        {props.status === "published" && <Badge variant="success">{t("toolbar.statusPublished")}</Badge>}
        {props.status === "unpublished" && <Badge variant="neutral">{t("toolbar.statusUnpublished")}</Badge>}
      </div>
      <div className="studio-toolbar-group">
        <button type="button" className="button-ghost button-icon" aria-label={t("toolbar.undo")} title={t("toolbar.undoShortcut")} disabled={!props.canUndo || !editable} onClick={props.onUndo}>
          ↶
        </button>
        <button type="button" className="button-ghost button-icon" aria-label={t("toolbar.redo")} title={t("toolbar.redoShortcut")} disabled={!props.canRedo || !editable} onClick={props.onRedo}>
          ↷
        </button>
        <select value={props.mode} onChange={(event) => props.onModeChange(event.target.value as EditorMode)} aria-label={t("toolbar.mode")}>
          {(["simple", "advanced", "expert"] as const).map((mode) => (
            <option key={mode} value={mode}>
              {t(`mode.${mode}`)}
            </option>
          ))}
        </select>
        <div className="studio-segmented" role="radiogroup" aria-label={t("toolbar.view")}>
          {(["design", "split", "preview"] as const).map((view) => (
            <button key={view} type="button" role="radio" aria-checked={props.view === view} className={props.view === view ? "button-toggle button-toggle-active" : "button-toggle"} onClick={() => props.onViewChange(view)}>
              {t(`toolbar.viewValue.${view}`)}
            </button>
          ))}
        </div>
        <select value={props.page.size} disabled={!editable} onChange={(event) => props.onPageSize(event.target.value as PageSetup["size"])} aria-label={t("toolbar.pageSize")}>
          {["A4", "A5", "A3", "Letter", "Legal", ...(props.page.size === "custom" ? ["custom"] : [])].map((size) => (
            <option key={size} value={size}>
              {t(`document.sizeValue.${size}`)}
            </option>
          ))}
        </select>
        <button type="button" className="button-ghost button-icon" disabled={!editable} aria-label={props.page.orientation === "portrait" ? t("toolbar.toLandscape") : t("toolbar.toPortrait")} title={props.page.orientation === "portrait" ? t("toolbar.toLandscape") : t("toolbar.toPortrait")} onClick={() => props.onOrientation(props.page.orientation === "portrait" ? "landscape" : "portrait")}>
          {props.page.orientation === "portrait" ? "▯" : "▭"}
        </button>
        <span className="studio-zoom">
          <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("toolbar.zoomOut")} onClick={() => props.onZoom(Math.max(0.4, Math.round((props.zoom - 0.1) * 10) / 10))}>
            −
          </button>
          <span>{Math.round(props.zoom * 100)}%</span>
          <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("toolbar.zoomIn")} onClick={() => props.onZoom(Math.min(2, Math.round((props.zoom + 0.1) * 10) / 10))}>
            +
          </button>
        </span>
      </div>
      <div className="studio-toolbar-group">
        {props.onDiscard && (
          <button type="button" className="button-ghost" onClick={props.onDiscard}>
            {t("toolbar.discard")}
          </button>
        )}
        {editable && (
          <button type="button" className="button-secondary" onClick={props.onSave} disabled={props.saveState === "saving" || props.saveState === "saved"}>
            {t("toolbar.save")}
          </button>
        )}
        {props.canPublish && (
          <button type="button" className="button-primary" onClick={props.onPublish} disabled={props.saveState !== "saved" || props.status !== "draft"} title={props.errorCount ? t("toolbar.publishBlocked", { count: props.errorCount }) : undefined}>
            {t("toolbar.publish")}
          </button>
        )}
      </div>
    </header>
  );
}
