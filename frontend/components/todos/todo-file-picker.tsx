"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { FileTypeIcon } from "@/components/files/file-type-icon";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import type { FileOverviewItem, TodoDetailFile } from "@/types/api";

const RESULT_LIMIT = 20;

/** Sucht unter den bereits hochgeladenen Dateien des Mandanten (GET /api/files) und meldet die
 * gewählte Datei. Treffer stehen direkt unter dem Suchfeld statt in einem schwebenden Panel,
 * damit das Todo-Popup sie nicht abschneidet. */
export function TodoFilePicker({ excludeIds, onPick }: { excludeIds: string[]; onPick: (file: TodoDetailFile) => void }) {
  const t = useTranslations("todos");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<FileOverviewItem[] | null>(null);
  const [active, setActive] = useState(0);

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

  const visible = (results ?? []).filter((file) => !excludeIds.includes(file.id));

  function pick(file: FileOverviewItem) {
    onPick({ id: file.id, original_name: file.original_name, mime_type: file.mime_type, file_size_bytes: file.file_size_bytes, content_url: file.content_url });
    setQuery("");
    setActive(0);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      if (visible.length) setActive((current) => (current + (event.key === "ArrowDown" ? 1 : visible.length - 1)) % visible.length);
    } else if (event.key === "Enter" && open && visible[active]) {
      event.preventDefault();
      pick(visible[active]);
    }
  }

  return <div className="todo-file-picker">
    <input
      className="dropdown-search-input"
      aria-label={t("filesSearchPlaceholder")}
      placeholder={t("filesSearchPlaceholder")}
      value={query}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(0); }}
      onKeyDown={onKeyDown}
    />
    {open && <div className="dropdown-panel todo-file-results" role="listbox" aria-label={t("filesLabel")}>
      <div className="dropdown-panel-scroll">
        {results === null ? <div className="dropdown-empty">{t("filesLoading")}</div>
          : visible.length === 0 ? <div className="dropdown-empty">{t("filesNoMatches")}</div>
          : visible.map((file, index) => <button
            key={file.id}
            type="button"
            role="option"
            tabIndex={-1}
            aria-selected={index === active}
            className={`dropdown-option todo-file-option${index === active ? " dropdown-option-active" : ""}`}
            // mousedown statt click: sonst schliesst das blur des Suchfelds die Liste vorher
            onMouseDown={(event) => { event.preventDefault(); pick(file); }}
          >
            <FileTypeIcon name={file.original_name} />
            <span className="todo-file-name">{file.original_name}</span>
            {file.file_size_bytes != null && <small className="muted">{formatFileSize(file.file_size_bytes)}</small>}
          </button>)}
      </div>
    </div>}
  </div>;
}
