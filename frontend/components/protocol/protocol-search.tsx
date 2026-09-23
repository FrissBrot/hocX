"use client";

import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { trimSectionName, visibleBlockTitle } from "@/components/protocol/protocol-editor-shared";
import { ProtocolElement, ProtocolElementBlock, ProtocolTodo } from "@/types/api";

// Ab wieviel Zeichen ein Treffer im Fliesstext (nicht im Kapitelnamen) ein Kapitel ins
// Ergebnis holt. Kurz-Query wie "an" wuerde sonst fast jedes Kapitel treffen und das
// Popup ueberladen - es bleibt primaer ein Sprungwerkzeug, kein Volltext-Suchergebnis.
const MIN_CONTENT_QUERY_LENGTH = 3;

type TextMatch = { index: number; length: number; wordBoundary: boolean };
type Snippet = { before: string; match: string; after: string };

type SearchResult = {
  element: ProtocolElement;
  number: number;
  titleMatch: TextMatch | null;
  snippet: Snippet | null;
};

type ProtocolSearchModalProps = {
  open: boolean;
  onClose: () => void;
  onSelect: (elementId: string) => void;
  elements: ProtocolElement[];
  todosByBlock: Record<string, ProtocolTodo[]>;
  textDrafts: Record<string, string>;
  protocolNumber: string;
};

function normalize(value: string): string {
  return value.toLocaleLowerCase("de-CH");
}

function firstMatch(haystack: string, needle: string): TextMatch | null {
  if (!needle) return null;
  const index = normalize(haystack).indexOf(normalize(needle));
  if (index === -1) return null;
  const before = haystack[index - 1];
  const wordBoundary = index === 0 || /[^\p{L}\p{N}]/u.test(before ?? " ");
  return { index, length: needle.length, wordBoundary };
}

function buildSnippet(text: string, match: TextMatch): Snippet {
  const CONTEXT = 42;
  const start = Math.max(0, match.index - CONTEXT);
  const end = Math.min(text.length, match.index + match.length + CONTEXT);
  return {
    before: (start > 0 ? "…" : "") + text.slice(start, match.index),
    match: text.slice(match.index, match.index + match.length),
    after: text.slice(match.index + match.length, end) + (end < text.length ? "…" : ""),
  };
}

/** Durchsuchbare Textfragmente eines Blocks: Titel/Label, eigener Inhalt (Live-Entwurf vor
 * gespeichertem Snapshot), sowie bei Todo-Bloecken die einzelnen Aufgabentexte. */
function blockSearchFragments(
  block: ProtocolElementBlock,
  todosByBlock: Record<string, ProtocolTodo[]>,
  textDrafts: Record<string, string>
): string[] {
  const fragments: string[] = [];
  const label = visibleBlockTitle(block);
  if (label) fragments.push(label);

  const isFreeText = block.element_type_code === "text" || block.element_type_code === "static_text";
  const text = (isFreeText ? textDrafts[block.id] ?? block.text_content : block.text_content) ?? "";
  if (text.trim()) fragments.push(text.trim());

  if (block.display_compiled_text?.trim()) fragments.push(block.display_compiled_text.trim());

  if (block.element_type_code === "todo") {
    for (const todo of todosByBlock[block.id] ?? []) {
      if (todo.task?.trim()) fragments.push(todo.task.trim());
    }
  }

  return fragments;
}

function highlightTitle(title: string, match: TextMatch | null) {
  if (!match) return title;
  return (
    <>
      {title.slice(0, match.index)}
      <mark className="protocol-search-highlight">{title.slice(match.index, match.index + match.length)}</mark>
      {title.slice(match.index + match.length)}
    </>
  );
}

export function ProtocolSearchModal({
  open,
  onClose,
  onSelect,
  elements,
  todosByBlock,
  textDrafts,
  protocolNumber,
}: ProtocolSearchModalProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    const raf = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(raf);
  }, [open]);

  const results = useMemo<SearchResult[]>(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      return elements.map((element, index) => ({ element, number: index + 1, titleMatch: null, snippet: null }));
    }

    const contentEligible = trimmed.length >= MIN_CONTENT_QUERY_LENGTH;
    const hits: SearchResult[] = [];

    elements.forEach((element, index) => {
      const titleMatch = firstMatch(trimSectionName(element.section_name_snapshot), trimmed);

      let bestSnippet: Snippet | null = null;
      let bestRank = 0;
      if (!titleMatch && contentEligible) {
        for (const block of element.blocks) {
          for (const fragment of blockSearchFragments(block, todosByBlock, textDrafts)) {
            const match = firstMatch(fragment, trimmed);
            if (!match) continue;
            const rank = match.wordBoundary ? 2 : 1;
            if (rank > bestRank) {
              bestRank = rank;
              bestSnippet = buildSnippet(fragment, match);
            }
          }
          if (bestRank === 2) break;
        }
      }

      if (titleMatch || bestSnippet) {
        hits.push({ element, number: index + 1, titleMatch, snippet: titleMatch ? null : bestSnippet });
      }
    });

    return hits;
  }, [elements, todosByBlock, textDrafts, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, results.length]);

  function selectResult(result: SearchResult) {
    onSelect(result.element.id);
    onClose();
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(results.length - 1, current + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const result = results[activeIndex];
      if (result) selectResult(result);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Kapitel suchen" hideHeader className="protocol-search-shell">
      <div className="protocol-search-field-row">
        <SearchInput
          ref={inputRef}
          value={query}
          onChange={setQuery}
          onKeyDown={handleInputKeyDown}
          placeholder={`Kapitel oder Wort in ${protocolNumber} suchen…`}
          className="protocol-search-input"
          aria-label="Kapitel oder Wort suchen"
        />
        <span className="dropdown-hint">Esc</span>
      </div>

      <div className="protocol-search-section-label">
        <span>Kapitel</span>
        {query.trim() ? <span>{results.length} Treffer</span> : null}
      </div>

      <div className="protocol-search-list" role="listbox" aria-label="Kapitel">
        {results.length === 0 ? (
          <div className="protocol-search-empty">Keine Treffer für „{query.trim()}“</div>
        ) : (
          results.map((result, index) => {
            const title = trimSectionName(result.element.section_name_snapshot);
            const subtitle = result.snippet
              ? null
              : result.element.blocks.map((block) => visibleBlockTitle(block)).filter(Boolean).join(" · ");
            const active = index === activeIndex;
            return (
              <button
                key={result.element.id}
                type="button"
                ref={(node) => {
                  itemRefs.current[index] = node;
                }}
                className={`protocol-search-item${active ? " protocol-search-item-active" : ""}`}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectResult(result)}
                role="option"
                aria-selected={active}
              >
                <span className="protocol-search-item-index">{result.number}</span>
                <span className="protocol-search-item-title">{highlightTitle(title, result.titleMatch)}</span>
                {result.snippet ? (
                  <span className="protocol-search-item-snippet">
                    {result.snippet.before}
                    <mark className="protocol-search-highlight">{result.snippet.match}</mark>
                    {result.snippet.after}
                  </span>
                ) : subtitle ? (
                  <span className="protocol-search-item-subtitle">{subtitle}</span>
                ) : null}
              </button>
            );
          })
        )}
      </div>

      <div className="protocol-search-footer">
        <span className="protocol-search-footer-hint">
          <span className="dropdown-hint">↑↓</span> Auswählen
        </span>
        <span className="protocol-search-footer-hint">
          <span className="dropdown-hint">↵</span> Hinspringen
        </span>
        <span className="protocol-search-footer-hint">
          <span className="dropdown-hint">Esc</span> Schliessen
        </span>
      </div>
    </Modal>
  );
}
