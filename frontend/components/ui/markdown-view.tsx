import { Fragment, type ReactNode } from "react";

import { findLinks } from "@/lib/utils/autolink";

// Statische Anzeige des Markdowns aus dem Rich-Text-Editor (rich-text-markdown.ts) ohne Tiptap und
// ohne HTML-Einfügen (kein innerHTML): der Text wird in React-Elemente zerlegt, React maskiert alles.
// Abgedeckt ist genau, was der Editor speichert: Absätze, harte Zeilenumbrüche, fett, kursiv,
// Aufzählungen und nummerierte Listen (auch verschachtelt), maskierte Zeichen und Entitäten von
// tiptap-markdown, nackte Links wie im Editor (lib/utils/autolink.ts, gleiche Regeln wie im PDF).
// Gebraucht im Protokoll-Editor für alle Textblöcke ausser dem aktiven (L4).

type ListNode = { ordered: boolean; start: number; items: ItemNode[] };
type ItemNode = { lines: string[]; children: ListNode[] };
type BlockNode = { kind: "paragraph"; lines: string[] } | { kind: "list"; list: ListNode };

const LIST_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };

/** Markdown in Absätze und Listen zerlegen (nur die Strukturen, die der Editor erzeugt). */
export function parseMarkdownBlocks(markdown: string): BlockNode[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks: BlockNode[] = [];
  let paragraph: string[] | null = null;
  // Stapel offener Listen mit ihrer Einrückung
  let stack: { indent: number; list: ListNode }[] = [];

  const closeParagraph = () => {
    if (paragraph && paragraph.length) blocks.push({ kind: "paragraph", lines: paragraph });
    paragraph = null;
  };
  const closeLists = () => {
    stack = [];
  };

  for (const raw of lines) {
    if (!raw.trim()) {
      closeParagraph();
      continue;
    }
    const match = LIST_ITEM.exec(raw);
    if (match) {
      closeParagraph();
      const indent = match[1].replace(/\t/g, "    ").length;
      const ordered = /\d/.test(match[2]);
      const item: ItemNode = { lines: [match[3]], children: [] };
      while (stack.length && indent < stack[stack.length - 1].indent) stack.pop();
      const top = stack[stack.length - 1];
      if (top && indent === top.indent && top.list.ordered === ordered) {
        top.list.items.push(item);
      } else if (top && indent > top.indent) {
        const parentItem = top.list.items[top.list.items.length - 1];
        const list: ListNode = { ordered, start: ordered ? Number.parseInt(match[2], 10) || 1 : 1, items: [item] };
        parentItem.children.push(list);
        stack.push({ indent, list });
      } else {
        const list: ListNode = { ordered, start: ordered ? Number.parseInt(match[2], 10) || 1 : 1, items: [item] };
        if (top) stack.pop();
        if (!stack.length) blocks.push({ kind: "list", list });
        else stack[stack.length - 1].list.items[stack[stack.length - 1].list.items.length - 1].children.push(list);
        stack.push({ indent, list });
      }
      continue;
    }
    // Eingerückte Fortsetzung eines Listenpunkts
    const top = stack[stack.length - 1];
    if (top && /^\s+/.test(raw) && !paragraph) {
      top.list.items[top.list.items.length - 1].lines.push(raw.trim());
      continue;
    }
    closeLists();
    (paragraph ??= []).push(raw);
  }
  closeParagraph();
  return blocks;
}

function decodeEntities(text: string): string {
  return text.replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, name: string) => ENTITIES[name] ?? _);
}

/** Text mit nackten Links in Knoten zerlegen. */
function linkify(text: string, keyPrefix: string): ReactNode[] {
  const links = findLinks(text);
  if (!links.length) return [text];
  const nodes: ReactNode[] = [];
  let pos = 0;
  links.forEach((link, index) => {
    if (link.from > pos) nodes.push(text.slice(pos, link.from));
    nodes.push(
      <a key={`${keyPrefix}-l${index}`} className="markdown-view-link" href={link.href} target="_blank" rel="noopener noreferrer">
        {text.slice(link.from, link.to)}
      </a>
    );
    pos = link.to;
  });
  if (pos < text.length) nodes.push(text.slice(pos));
  return nodes;
}

// Maskierte Zeichen (\* \_ \\ …) vor der Hervorhebungssuche durch Platzhalter ersetzen
const ESCAPED = /\\([\\`*_{}[\]()#+\-.!>~|])/g;
const PLACEHOLDER_BASE = 0xe000;

function protectEscapes(text: string): string {
  return text.replace(ESCAPED, (_, char: string) => String.fromCharCode(PLACEHOLDER_BASE + char.charCodeAt(0)));
}

function restoreEscapes(text: string): string {
  return text.replace(/[-]/g, (char) => String.fromCharCode(char.charCodeAt(0) - PLACEHOLDER_BASE));
}

// Hervorhebungen: fett vor kursiv; «_» nur an Wortgrenzen (wie CommonMark)
const EMPHASIS = [
  { re: /\*\*(?=\S)([\s\S]*?\S)\*\*/, tag: "strong" as const },
  { re: /(?<![\p{L}\p{N}])__(?=\S)([\s\S]*?\S)__(?![\p{L}\p{N}])/u, tag: "strong" as const },
  { re: /\*(?=\S)([\s\S]*?\S)\*/, tag: "em" as const },
  { re: /(?<![\p{L}\p{N}])_(?=\S)([\s\S]*?\S)_(?![\p{L}\p{N}])/u, tag: "em" as const },
];

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  let best: { index: number; length: number; inner: string; tag: "strong" | "em" } | null = null;
  for (const { re, tag } of EMPHASIS) {
    const match = re.exec(text);
    if (match && (best === null || match.index < best.index)) best = { index: match.index, length: match[0].length, inner: match[1], tag };
  }
  if (!best) return linkify(decodeEntities(restoreEscapes(text)), keyPrefix);
  const before = text.slice(0, best.index);
  const after = text.slice(best.index + best.length);
  const Tag = best.tag;
  return [
    ...(before ? renderInline(before, `${keyPrefix}a`) : []),
    <Tag key={`${keyPrefix}-${best.index}`}>{renderInline(best.inner, `${keyPrefix}i`)}</Tag>,
    ...(after ? renderInline(after, `${keyPrefix}b`) : []),
  ];
}

/** Zeilen eines Absatzes: «\» oder zwei Leerzeichen am Ende = harter Umbruch, sonst Leerzeichen. */
function renderLines(lines: string[], keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  lines.forEach((line, index) => {
    const hard = /\\$/.test(line) || / {2,}$/.test(line);
    const content = line.replace(/\\$/, "").replace(/\s+$/, "").replace(/^\s+/, "");
    nodes.push(<Fragment key={`${keyPrefix}-${index}`}>{renderInline(protectEscapes(content), `${keyPrefix}-${index}`)}</Fragment>);
    if (index < lines.length - 1) nodes.push(hard ? <br key={`${keyPrefix}-br${index}`} /> : " ");
  });
  return nodes;
}

function renderList(list: ListNode, key: string): ReactNode {
  const items = list.items.map((item, index) => (
    <li key={`${key}-${index}`}>
      {renderLines(item.lines, `${key}-${index}`)}
      {item.children.map((child, childIndex) => renderList(child, `${key}-${index}-${childIndex}`))}
    </li>
  ));
  return list.ordered ? (
    <ol key={key} start={list.start === 1 ? undefined : list.start}>{items}</ol>
  ) : (
    <ul key={key}>{items}</ul>
  );
}

export function MarkdownView({ markdown, className, placeholder }: { markdown: string; className?: string; placeholder?: string }) {
  const blocks = parseMarkdownBlocks(markdown);
  if (!blocks.length) {
    return placeholder ? <p className={`markdown-view markdown-view-empty${className ? ` ${className}` : ""}`}>{placeholder}</p> : null;
  }
  return (
    <div className={`markdown-view${className ? ` ${className}` : ""}`}>
      {blocks.map((block, index) =>
        block.kind === "paragraph" ? <p key={`p${index}`}>{renderLines(block.lines, `p${index}`)}</p> : renderList(block.list, `l${index}`)
      )}
    </div>
  );
}
