// Word-level diff for "Änderungen nachverfolgen" (track changes). Tokenizes on
// whitespace boundaries (keeping whitespace itself as tokens so the merged
// output reproduces the original spacing/line breaks exactly) and finds the
// minimal edit sequence via a standard LCS dynamic-programming table.
export type DiffOp = "equal" | "insert" | "delete";

export interface DiffToken {
  op: DiffOp;
  text: string;
}

function tokenize(text: string): string[] {
  return text.match(/\s+|\S+/g) ?? [];
}

export interface IndexedDiffToken {
  op: DiffOp;
  text: string;
  // Character offsets into the original oldText/newText strings. Only the
  // side(s) relevant to the op are meaningful: "delete" only sets old*,
  // "insert" only sets new*, "equal" sets both (contiguous by construction,
  // since tokenize() covers the source string with no gaps).
  oldStart: number;
  oldEnd: number;
  newStart: number;
  newEnd: number;
}

function tokenizeWithOffsets(text: string): { value: string; start: number; end: number }[] {
  const result: { value: string; start: number; end: number }[] = [];
  const re = /\s+|\S+/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    result.push({ value: match[0], start: match.index, end: match.index + match[0].length });
  }
  return result;
}

function mergeAdjacentIndexed(tokens: IndexedDiffToken[]): IndexedDiffToken[] {
  const merged: IndexedDiffToken[] = [];
  for (const token of tokens) {
    const last = merged[merged.length - 1];
    if (last && last.op === token.op) {
      last.text += token.text;
      if (token.op !== "insert") last.oldEnd = token.oldEnd;
      if (token.op !== "delete") last.newEnd = token.newEnd;
    } else {
      merged.push({ ...token });
    }
  }
  return merged;
}

// Same LCS word-diff as diffWords(), but also reports the character range
// each token occupies in the original oldText/newText - needed to map diff
// tokens back onto real document positions (e.g. ProseMirror decorations)
// instead of just re-rendering the diff as standalone text.
export function diffWordsIndexed(oldText: string, newText: string): IndexedDiffToken[] {
  const a = tokenizeWithOffsets(oldText);
  const b = tokenizeWithOffsets(newText);
  const n = a.length;
  const m = b.length;

  if (n * m > MAX_TABLE_CELLS) {
    const tokens: IndexedDiffToken[] = [];
    if (oldText) tokens.push({ op: "delete", text: oldText, oldStart: 0, oldEnd: oldText.length, newStart: -1, newEnd: -1 });
    if (newText) tokens.push({ op: "insert", text: newText, oldStart: -1, oldEnd: -1, newStart: 0, newEnd: newText.length });
    return tokens;
  }

  const dp: Uint32Array[] = new Array(n + 1);
  for (let i = 0; i <= n; i++) dp[i] = new Uint32Array(m + 1);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i].value === b[j].value ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const tokens: IndexedDiffToken[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i].value === b[j].value) {
      tokens.push({ op: "equal", text: a[i].value, oldStart: a[i].start, oldEnd: a[i].end, newStart: b[j].start, newEnd: b[j].end });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      tokens.push({ op: "delete", text: a[i].value, oldStart: a[i].start, oldEnd: a[i].end, newStart: -1, newEnd: -1 });
      i++;
    } else {
      tokens.push({ op: "insert", text: b[j].value, oldStart: -1, oldEnd: -1, newStart: b[j].start, newEnd: b[j].end });
      j++;
    }
  }
  while (i < n) {
    tokens.push({ op: "delete", text: a[i].value, oldStart: a[i].start, oldEnd: a[i].end, newStart: -1, newEnd: -1 });
    i++;
  }
  while (j < m) {
    tokens.push({ op: "insert", text: b[j].value, oldStart: -1, oldEnd: -1, newStart: b[j].start, newEnd: b[j].end });
    j++;
  }

  return mergeAdjacentIndexed(tokens);
}

function mergeAdjacent(tokens: DiffToken[]): DiffToken[] {
  const merged: DiffToken[] = [];
  for (const token of tokens) {
    const last = merged[merged.length - 1];
    if (last && last.op === token.op) {
      last.text += token.text;
    } else {
      merged.push({ ...token });
    }
  }
  return merged;
}

// LCS table is O(n*m) time/space - fine for protocol-length text (a few
// hundred words), but guarded against pathological huge inputs where the
// table would get too large to compute synchronously in the browser.
const MAX_TABLE_CELLS = 4_000_000;

export function diffWords(oldText: string, newText: string): DiffToken[] {
  const a = tokenize(oldText);
  const b = tokenize(newText);
  const n = a.length;
  const m = b.length;

  if (n * m > MAX_TABLE_CELLS) {
    const tokens: DiffToken[] = [];
    if (oldText) tokens.push({ op: "delete", text: oldText });
    if (newText) tokens.push({ op: "insert", text: newText });
    return tokens;
  }

  const dp: Uint32Array[] = new Array(n + 1);
  for (let i = 0; i <= n; i++) dp[i] = new Uint32Array(m + 1);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const tokens: DiffToken[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      tokens.push({ op: "equal", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      tokens.push({ op: "delete", text: a[i] });
      i++;
    } else {
      tokens.push({ op: "insert", text: b[j] });
      j++;
    }
  }
  while (i < n) {
    tokens.push({ op: "delete", text: a[i] });
    i++;
  }
  while (j < m) {
    tokens.push({ op: "insert", text: b[j] });
    j++;
  }

  return mergeAdjacent(tokens);
}
