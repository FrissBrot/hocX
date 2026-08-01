import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

import { diffWordsIndexed } from "@/lib/word-diff";

// Renders "Änderungen nachverfolgen" (track changes) INLINE, in the actual
// editable document - like Word - instead of as a separate before/after
// preview. Removed words are inserted as non-editable widget decorations
// (struck through) at the point they were removed; words still present but
// added since the baseline are underlined in place. Nothing here touches the
// real document content - it's pure decoration, so it never affects what
// gets saved.
//
// Diffing runs in two passes: paragraphs are aligned first (LCS on whole
// paragraph text), THEN words are diffed within each paired paragraph. A
// single flat word-diff across the whole block would anchor every deleted
// word at the position of the last surviving word anywhere in the block,
// which visibly drags e.g. a deleted second paragraph up into the first one
// whenever the paragraph structure itself changed.

function stripMarkdownLine(line: string): string {
  let stripped = line.replace(/^\s*(?:[-*+]|\d+\.)\s+/, "");
  stripped = stripped.replace(/\*\*(.+?)\*\*/g, "$1");
  stripped = stripped.replace(/\*(.+?)\*/g, "$1");
  stripped = stripped.replace(/\\$/, "");
  return stripped;
}

// Splits the baseline markdown into paragraph-equivalent units matching how
// the live ProseMirror doc is split into textblocks: a blank-line-separated
// group of lines is one paragraph (internal lines joined back with "\n" for
// hard breaks), while each list-item line is its own unit (matching one
// listItem>paragraph textblock per item).
function extractBaselineParagraphs(markdown: string): string[] {
  const lines = markdown.split("\n");
  const paragraphs: string[] = [];
  let buffer: string[] = [];
  const flush = () => {
    if (buffer.length > 0) {
      paragraphs.push(buffer.map(stripMarkdownLine).join("\n"));
      buffer = [];
    }
  };
  for (const line of lines) {
    if (line.trim() === "") {
      flush();
      continue;
    }
    if (/^\s*(?:[-*+]|\d+\.)\s+/.test(line)) {
      flush();
      paragraphs.push(stripMarkdownLine(line));
    } else {
      buffer.push(line);
    }
  }
  flush();
  return paragraphs;
}

interface LiveParagraph {
  text: string;
  posMap: number[];
  paraStart: number;
}

// One entry per textblock (paragraph, or listItem>paragraph) in document
// order, each with its own plain text and a char-index -> doc-position map.
function extractLiveParagraphs(doc: ProseMirrorNode): LiveParagraph[] {
  const paragraphs: LiveParagraph[] = [];
  let current: LiveParagraph | null = null;

  doc.descendants((node, pos) => {
    if (node.isTextblock) {
      current = { text: "", posMap: [], paraStart: pos + 1 };
      paragraphs.push(current);
      return true;
    }
    if (node.type.name === "hardBreak" && current) {
      current.text += "\n";
      current.posMap.push(pos);
      return false;
    }
    if (node.isText && current) {
      const value = node.text ?? "";
      for (let i = 0; i < value.length; i++) {
        current.text += value[i];
        current.posMap.push(pos + i);
      }
      return false;
    }
    return true;
  });

  return paragraphs;
}

interface ParagraphOp {
  op: "equal" | "delete" | "insert";
  oldIndex?: number;
  newIndex?: number;
}

function diffParagraphs(a: string[], b: string[]): ParagraphOp[] {
  const n = a.length;
  const m = b.length;
  const dp: Uint32Array[] = new Array(n + 1);
  for (let i = 0; i <= n; i++) dp[i] = new Uint32Array(m + 1);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: ParagraphOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ op: "equal", oldIndex: i, newIndex: j });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ op: "delete", oldIndex: i });
      i++;
    } else {
      ops.push({ op: "insert", newIndex: j });
      j++;
    }
  }
  while (i < n) {
    ops.push({ op: "delete", oldIndex: i });
    i++;
  }
  while (j < m) {
    ops.push({ op: "insert", newIndex: j });
    j++;
  }
  return ops;
}

function makeStrikeWidget(text: string, block: boolean): HTMLElement {
  const el = document.createElement(block ? "div" : "span");
  el.className = block ? "tracked-strike tracked-word-widget tracked-word-widget-block" : "tracked-strike tracked-word-widget";
  el.textContent = text;
  el.contentEditable = "false";
  return el;
}

// Word-level diff between one old (baseline) paragraph and its paired live
// paragraph - anchors deleted-word widgets and inserted-word underlines to
// real positions WITHIN that specific paragraph, never outside it.
function diffParagraphWords(oldText: string, newPara: LiveParagraph, decorations: Decoration[]) {
  if (oldText === newPara.text) return;
  const tokens = diffWordsIndexed(oldText, newPara.text);
  let anchor = newPara.posMap.length > 0 ? newPara.posMap[0] : newPara.paraStart;
  for (const token of tokens) {
    if (token.op === "delete") {
      const removed = oldText.slice(token.oldStart, token.oldEnd);
      if (removed.trim().length === 0) continue;
      const at = anchor;
      decorations.push(Decoration.widget(at, () => makeStrikeWidget(removed, false), { side: -1 }));
      continue;
    }
    const fromPos = newPara.posMap[token.newStart];
    const toPos = newPara.posMap[token.newEnd - 1] + 1;
    anchor = toPos;
    if (token.op === "insert") {
      decorations.push(Decoration.inline(fromPos, toPos, { class: "tracked-underline" }));
    }
  }
}

function markWholeParagraphInserted(para: LiveParagraph, decorations: Decoration[]) {
  if (para.posMap.length === 0) return;
  const fromPos = para.posMap[0];
  const toPos = para.posMap[para.posMap.length - 1] + 1;
  decorations.push(Decoration.inline(fromPos, toPos, { class: "tracked-underline" }));
}

function peekNextNewIndex(ops: ParagraphOp[], fromIndex: number, fallback: number): number {
  for (let k = fromIndex; k < ops.length; k++) {
    if (ops[k].newIndex !== undefined) return ops[k].newIndex as number;
  }
  return fallback;
}

export interface TrackedChangesOptions {
  getBaseline: () => string | null | undefined;
}

export const TrackedChanges = Extension.create<TrackedChangesOptions>({
  name: "trackedChanges",

  addOptions() {
    return { getBaseline: () => undefined };
  },

  addProseMirrorPlugins() {
    const options = this.options;
    return [
      new Plugin({
        key: new PluginKey("trackedChanges"),
        props: {
          decorations(state) {
            const baseline = options.getBaseline();
            if (!baseline) return DecorationSet.empty;

            const baselineParagraphs = extractBaselineParagraphs(baseline);
            const liveParagraphs = extractLiveParagraphs(state.doc);
            const liveTexts = liveParagraphs.map((p) => p.text);

            const identical =
              baselineParagraphs.length === liveTexts.length && baselineParagraphs.every((text, idx) => text === liveTexts[idx]);
            if (identical) return DecorationSet.empty;

            const ops = diffParagraphs(baselineParagraphs, liveTexts);
            const decorations: Decoration[] = [];
            let i = 0;

            while (i < ops.length) {
              if (ops[i].op === "equal") {
                i++;
                continue;
              }

              const deleteRun: number[] = [];
              while (i < ops.length && ops[i].op === "delete") {
                deleteRun.push(ops[i].oldIndex as number);
                i++;
              }
              const insertRun: number[] = [];
              while (i < ops.length && ops[i].op === "insert") {
                insertRun.push(ops[i].newIndex as number);
                i++;
              }

              const nextNewIndex = peekNextNewIndex(ops, i, liveParagraphs.length);
              const fallbackAnchor = nextNewIndex < liveParagraphs.length ? liveParagraphs[nextNewIndex].paraStart : state.doc.content.size;

              const pairedCount = Math.min(deleteRun.length, insertRun.length);
              for (let k = 0; k < pairedCount; k++) {
                diffParagraphWords(baselineParagraphs[deleteRun[k]], liveParagraphs[insertRun[k]], decorations);
              }
              for (let k = pairedCount; k < deleteRun.length; k++) {
                const text = baselineParagraphs[deleteRun[k]];
                if (text.trim().length === 0) continue;
                decorations.push(Decoration.widget(fallbackAnchor, () => makeStrikeWidget(text, true), { side: -1 }));
              }
              for (let k = pairedCount; k < insertRun.length; k++) {
                markWholeParagraphInserted(liveParagraphs[insertRun[k]], decorations);
              }
            }

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
