/**
 * Treffer der globalen Suche (Ctrl+K) für Einträge, die das Frontend selbst kennt (Menüs,
 * Einstellungen, Aktionen). Gross-/Kleinschreibung, Umlaute und Akzente spielen keine Rolle;
 * jedes Wort der Eingabe muss vorkommen (Titel, Bereich oder Suchbegriffe). Ein Tippfehler je
 * Wort (ab 5 Buchstaben) wird verziehen - solche Treffer stehen zuunterst.
 */
export function foldText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ß/g, "ss")
    .toLowerCase()
    .trim();
}

export type Matchable = { label: string; sublabel?: string; keywords?: string };

/** 0 = kein Treffer; höher = besser (Titel beginnt mit … > Wortanfang im Titel > irgendwo). */
export function matchScore(entry: Matchable, query: string): number {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return 0;
  const label = foldText(entry.label);
  const haystack = `${label} ${foldText(entry.sublabel ?? "")} ${foldText(entry.keywords ?? "")}`;
  if (!words.every((word) => haystack.includes(word))) {
    const tokens = haystack.split(/[^a-z0-9]+/).filter(Boolean);
    return words.every((word) => haystack.includes(word) || (word.length >= 5 && tokens.some((token) => nearlyStartsWith(token, word))))
      ? 0.5
      : 0;
  }
  const whole = words.join(" ");
  if (label.startsWith(whole)) return 4;
  if (label.split(/[\s/–-]+/).some((part) => part.startsWith(words[0]))) return 3;
  if (words.every((word) => label.includes(word))) return 2;
  return 1;
}

export function rankEntries<T extends Matchable>(entries: T[], query: string, limit = 8): T[] {
  return entries
    .map((entry, index) => ({ entry, index, score: matchScore(entry, query) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, limit)
    .map((item) => item.entry);
}

/** Beginnt das Wort mit dem Gesuchten bis auf einen Tippfehler (vertauscht, ein Buchstabe zu
 * viel/zu wenig/falsch)? «setings», «verlauff», «protkoll» finden ihr Ziel. */
function nearlyStartsWith(token: string, word: string): boolean {
  for (const length of [word.length - 1, word.length, word.length + 1]) {
    if (length < 4 || token.length < length) continue;
    if (withinOneEdit(token.slice(0, length), word)) return true;
  }
  return false;
}

function withinOneEdit(a: string, b: string): boolean {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i += 1;
      j += 1;
      continue;
    }
    edits += 1;
    if (edits > 1) return false;
    if (a.length === b.length) {
      // Vertauschte Nachbarn zählen als ein Fehler
      if (a[i + 1] === b[j] && a[i] === b[j + 1]) {
        i += 2;
        j += 2;
        continue;
      }
      i += 1;
      j += 1;
    } else if (a.length > b.length) i += 1;
    else j += 1;
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

export type HighlightSegment = { text: string; hit: boolean };

/**
 * Teilt einen Titel in Abschnitte mit und ohne Treffer, für die Hervorhebung in der Suche.
 * Dieselbe Faltung wie matchScore (Umlaute, Akzente, ß, Gross/Klein); jedes Wort der Eingabe wird
 * an jeder Fundstelle markiert. Tippfehler-Treffer (score 0.5) bleiben ohne Markierung.
 */
export function highlightMatch(label: string, query: string): HighlightSegment[] {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (words.length === 0 || !label) return [{ text: label, hit: false }];
  // gefalteter Titel + Zuordnung jedes gefalteten Zeichens zum Originalzeichen
  let folded = "";
  const origin: number[] = [];
  Array.from(label).forEach((char, index) => {
    const part = char.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss").toLowerCase();
    for (const piece of part) {
      folded += piece;
      origin.push(index);
    }
  });
  const chars = Array.from(label);
  const marked = new Array<boolean>(chars.length).fill(false);
  for (const word of words) {
    let from = folded.indexOf(word);
    while (from !== -1) {
      for (let i = from; i < from + word.length; i += 1) marked[origin[i]] = true;
      from = folded.indexOf(word, from + word.length);
    }
  }
  const segments: HighlightSegment[] = [];
  chars.forEach((char, index) => {
    const last = segments[segments.length - 1];
    if (last && last.hit === marked[index]) last.text += char;
    else segments.push({ text: char, hit: marked[index] });
  });
  return segments;
}
