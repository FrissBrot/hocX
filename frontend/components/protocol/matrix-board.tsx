"use client";

// Darstellung der Matrix im Protokoll-Editor (Design «Protokoll-Editor v2»): Kopfzeile mit
// Spaltenquelle und Umschalter Karten/Tabelle, je Spalte eine Karte im Mauerwerk-Layout und
// eine Tabellenansicht mit Zusammenfassungen. Die Zelleninhalte und das Speichern bleiben im
// focused-element-editor; hier liegen nur die wiederkehrenden Darstellungsbausteine.

import { ReactNode, useState } from "react";
import { useTranslations } from "next-intl";

export type MatrixView = "cards" | "table";

const VIEW_STORAGE_KEY = "hocx.protocol.matrixView";
const COLUMN_COLORS = 5;

/** Zuletzt gewählte Ansicht (pro Browser), Vorgabe Karten. */
export function readStoredMatrixView(): MatrixView {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === "table" ? "table" : "cards";
  } catch {
    return "cards";
  }
}

export function storeMatrixView(view: MatrixView) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Ohne Speicher gilt die Wahl nur bis zum Neuladen
  }
}

export function matrixColumnColorClass(index: number) {
  return `matrix-board-color-${(index % COLUMN_COLORS) + 1}`;
}

export function matrixInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function MatrixBoardHeader({
  source,
  view,
  onViewChange,
  actions,
}: {
  source: string | null;
  view: MatrixView;
  onViewChange: (view: MatrixView) => void;
  actions?: ReactNode;
}) {
  const t = useTranslations("protocols.matrixBoard");
  return (
    <div className="matrix-board-head">
      <span className="matrix-board-eyebrow">{t("title")}</span>
      {source ? (
        <span className="matrix-board-source" title={t("sourceTitle")}>
          <span className="matrix-board-source-icon" aria-hidden="true">↻</span>
          {source}
        </span>
      ) : null}
      <span className="matrix-board-head-spacer" />
      {actions}
      <div className="matrix-board-views" role="group" aria-label={t("viewLabel")}>
        {(["cards", "table"] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={view === option}
            className={`matrix-board-view${view === option ? " matrix-board-view-active" : ""}`}
            onClick={() => onViewChange(option)}
          >
            {option === "cards" ? t("viewCards") : t("viewTable")}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Zeilenbezeichnung einer Karte, optional mit «gesperrt» (Zeile aus der Vorlage fixiert). */
export function MatrixRowLabel({ label, locked, extra }: { label: string; locked: boolean; extra?: ReactNode }) {
  const t = useTranslations("protocols.matrixBoard");
  return (
    <span className="matrix-board-row-label">
      <span className="matrix-board-row-label-text">{label}</span>
      {locked ? (
        <span className="matrix-board-locked" title={t("lockedTitle")}>
          {t("locked")}
        </span>
      ) : null}
      {extra}
    </span>
  );
}

/** Leere Zelle: Link zum Hinzufügen oder ein Strich, wenn nichts geändert werden kann. */
export function MatrixEmptyValue({ addLabel, onAdd }: { addLabel?: string; onAdd?: () => void }) {
  if (onAdd && addLabel) {
    return (
      <button type="button" className="matrix-board-add-link" onClick={onAdd}>
        + {addLabel}
      </button>
    );
  }
  return <span className="matrix-board-dash">—</span>;
}

export function MatrixPeopleChips({
  names,
  onEdit,
  onAdd,
}: {
  names: string[];
  /** Klick auf eine Person öffnet die Auswahl (bearbeitbar) */
  onEdit?: () => void;
  /** Runder «+»-Knopf für weitere Personen */
  onAdd?: () => void;
}) {
  const t = useTranslations("protocols.matrixBoard");
  return (
    <div className="matrix-board-people">
      {names.map((name, index) =>
        onEdit ? (
          <button key={`${name}-${index}`} type="button" className="matrix-board-person matrix-board-person-button" onClick={onEdit}>
            <span className="matrix-board-person-avatar" aria-hidden="true">{matrixInitials(name)}</span>
            {name}
          </button>
        ) : (
          <span key={`${name}-${index}`} className="matrix-board-person">
            <span className="matrix-board-person-avatar" aria-hidden="true">{matrixInitials(name)}</span>
            {name}
          </span>
        )
      )}
      {onAdd ? (
        <button type="button" className="matrix-board-person-add" onClick={onAdd} title={t("addPersonTitle")} aria-label={t("addPersonTitle")}>
          +
        </button>
      ) : null}
    </div>
  );
}

/** Ein gewählter Termin; bearbeitbar öffnet ein Klick die Auswahl (renderPicker). */
export function MatrixEventValue({
  title,
  date,
  renderPicker,
}: {
  title: string;
  date: string;
  renderPicker?: (close: () => void) => ReactNode;
}) {
  const t = useTranslations("protocols.matrixBoard");
  const [editing, setEditing] = useState(false);
  if (editing && renderPicker) return <>{renderPicker(() => setEditing(false))}</>;
  const content = (
    <>
      <span className="matrix-board-event-title">{title}</span>
      <span className="matrix-board-event-date">{date}</span>
    </>
  );
  return renderPicker ? (
    <button type="button" className="matrix-board-event matrix-board-event-button" title={t("changeEvent")} onClick={() => setEditing(true)}>
      {content}
    </button>
  ) : (
    <div className="matrix-board-event">{content}</div>
  );
}

export function MatrixEventChips({ events }: { events: Array<{ id: string; date: string | null; label: string; muted?: string; past?: boolean }> }) {
  return (
    <div className="matrix-board-chips">
      {events.map((entry) => (
        <span key={entry.id} className={`matrix-board-chip${entry.past ? " matrix-board-chip-past" : ""}`}>
          {entry.date ? <b>{entry.date}</b> : null}
          {entry.label}
          {entry.muted ? <span className="matrix-board-chip-muted">{entry.muted}</span> : null}
        </span>
      ))}
    </div>
  );
}

export function MatrixAddColumnCard({ onClick }: { onClick: () => void }) {
  const t = useTranslations("protocols.matrixBoard");
  return (
    <button type="button" className="matrix-board-add-column" onClick={onClick}>
      + {t("addColumn")}
    </button>
  );
}

export type MatrixTableColumn = { id: string; name: string; colorIndex: number };
export type MatrixTableRow = { id: string; label: string; locked: boolean; cells: string[] };

export function MatrixTableView({ columns, rows }: { columns: MatrixTableColumn[]; rows: MatrixTableRow[] }) {
  const t = useTranslations("protocols.matrixBoard");
  return (
    <div className="matrix-board-table-wrap">
      <table className="matrix-board-table" style={{ minWidth: `${160 + columns.length * 170}px` }}>
        <thead>
          <tr>
            <th className="matrix-board-table-corner" aria-label={t("rowHeader")} />
            {columns.map((column) => (
              <th key={column.id} scope="col" className="matrix-board-table-col">
                <span className="matrix-board-table-col-name">
                  <span className={`matrix-board-swatch ${matrixColumnColorClass(column.colorIndex)}`} aria-hidden="true" />
                  {column.name}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th scope="row" className="matrix-board-table-row">
                <div className="matrix-board-table-row-inner">
                  <span>{row.label}</span>
                  {row.locked ? <span className="matrix-board-table-row-meta">{t("locked")}</span> : null}
                </div>
              </th>
              {row.cells.map((cell, index) => (
                <td key={columns[index]?.id ?? index} className={cell ? undefined : "matrix-board-table-empty"}>
                  {cell || "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
