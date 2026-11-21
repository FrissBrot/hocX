"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { FileTypeIcon } from "@/components/files/file-type-icon";
import { computePopoverPosition } from "@/components/ui/popover";
import { browserApiFetch } from "@/lib/api/client";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { formatFileSize } from "@/lib/utils/format";
import type { FileOverviewItem, TodoDetailFile } from "@/types/api";

const RESULT_LIMIT = 20;
// Höhe der Trefferliste (.dropdown-panel-scroll max-height 220 px + Rahmen/Abstand) für die
// Entscheidung «unter oder über dem Feld öffnen».
const ESTIMATED_PANEL_HEIGHT = 240;

/** Sucht unter den bereits hochgeladenen Dateien des Mandanten (GET /api/files) und meldet die
 * gewählte Datei. Die Trefferliste liegt als Portal über dem Dialog (--z-portal, wie
 * SearchableSelect): im Fluss unter dem Feld machte sie das Pendenz-Popup beim Öffnen höher.
 *
 * Mit `onUploadFiles` zusätzlich: Hinweis «oder ins Fenster ziehen» im Feld und als letzter
 * Eintrag der Liste «Datei hochladen …» (Tastatur-Alternative zum Ziehen, öffnet die
 * Dateiauswahl des Systems). */
export function TodoFilePicker({ excludeIds, onPick, onUploadFiles }: {
  excludeIds: string[];
  onPick: (file: TodoDetailFile) => void;
  onUploadFiles?: (files: File[]) => void;
}) {
  const t = useTranslations("todos");
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<FileOverviewItem[] | null>(null);
  const [active, setActive] = useState(0);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // Escape schliesst zuerst die offene Liste, nicht den Pendenz-Dialog darunter (Popup-Stapel).
  usePopupEscape(open, () => setOpen(false), panelRef);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ limit: String(RESULT_LIMIT) });
      if (query.trim()) params.set("search", query.trim());
      browserApiFetch<FileOverviewItem[]>(`/api/files?${params.toString()}`)
        .then((items) => { if (!cancelled) setResults(items); })
        .catch(() => { if (!cancelled) setResults([]); });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [open, query]);

  // Position vor dem Zeichnen setzen und beim Scrollen des Dialogs/Fensters nachführen.
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const input = inputRef.current;
      if (!input) return;
      const rect = input.getBoundingClientRect();
      setPanelStyle({ ...computePopoverPosition(rect, "start", 4, { estimatedHeight: ESTIMATED_PANEL_HEIGHT }), width: rect.width });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  const visible = (results ?? []).filter((file) => !excludeIds.includes(file.id));
  const optionCount = visible.length + (onUploadFiles ? 1 : 0);
  const uploadIndex = onUploadFiles ? visible.length : -1;
  const activeIndex = optionCount ? Math.min(active, optionCount - 1) : -1;

  function pick(file: FileOverviewItem) {
    onPick({ id: file.id, original_name: file.original_name, mime_type: file.mime_type, file_size_bytes: file.file_size_bytes, content_url: file.content_url });
    setQuery("");
    setActive(0);
  }

  function chooseUpload() {
    setOpen(false);
    fileInputRef.current?.click();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      if (optionCount) setActive((activeIndex + (event.key === "ArrowDown" ? 1 : optionCount - 1)) % optionCount);
    } else if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      if (activeIndex === uploadIndex) chooseUpload();
      else if (visible[activeIndex]) pick(visible[activeIndex]);
    }
  }

  const optionId = (index: number) => `${listId}-option-${index}`;
  const showHint = !!onUploadFiles && !query;

  return <div className={`todo-file-picker${showHint ? " todo-file-picker-with-hint" : ""}`}>
    <div className="todo-file-search">
      <input
        ref={inputRef}
        className="dropdown-search-input"
        role="combobox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={open && activeIndex >= 0 ? optionId(activeIndex) : undefined}
        aria-label={t("filesSearchPlaceholder")}
        placeholder={t("filesSearchPlaceholder")}
        value={query}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(0); }}
        onKeyDown={onKeyDown}
      />
      {showHint && <span className="todo-file-drop-hint" aria-hidden="true">{t("fileDrop.searchHint")}</span>}
    </div>
    {onUploadFiles && <input
      ref={fileInputRef}
      type="file"
      multiple
      hidden
      tabIndex={-1}
      aria-hidden="true"
      data-testid="todo-file-upload-input"
      onChange={(event) => {
        const files = Array.from(event.target.files ?? []);
        event.target.value = "";
        if (files.length) onUploadFiles(files);
      }}
    />}
    {open && typeof document !== "undefined" && createPortal(
      <div ref={panelRef} id={listId} className="dropdown-panel todo-file-results" role="listbox" aria-label={t("filesLabel")} style={panelStyle}>
        <div className="dropdown-panel-scroll">
          {results === null ? <div className="dropdown-empty">{t("filesLoading")}</div>
            : visible.length === 0 ? <div className="dropdown-empty">{t("filesNoMatches")}</div>
            : visible.map((file, index) => <button
              key={file.id}
              id={optionId(index)}
              type="button"
              role="option"
              tabIndex={-1}
              aria-selected={index === activeIndex}
              className={`dropdown-option todo-file-option${index === activeIndex ? " dropdown-option-active" : ""}`}
              // mousedown hält den Fokus im Suchfeld (sonst schliesst dessen blur die Liste vorher),
              // ausgelöst wird per click - so auch per Tastatur
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(file)}
            >
              <FileTypeIcon name={file.original_name} />
              <span className="todo-file-name">{file.original_name}</span>
              {file.file_size_bytes != null && <small className="muted">{formatFileSize(file.file_size_bytes)}</small>}
            </button>)}
          {onUploadFiles && <button
            id={optionId(uploadIndex)}
            type="button"
            role="option"
            tabIndex={-1}
            aria-selected={uploadIndex === activeIndex}
            className={`dropdown-option todo-file-option todo-file-upload-option${uploadIndex === activeIndex ? " dropdown-option-active" : ""}`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={chooseUpload}
          >
            <span className="todo-file-upload-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V5m0 0-4 4m4-4 4 4" /><path d="M5 15v2.5A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15" /></svg>
            </span>
            <span className="todo-file-name">{t("fileDrop.uploadOption")}</span>
          </button>}
        </div>
      </div>,
      document.body,
    )}
  </div>;
}
