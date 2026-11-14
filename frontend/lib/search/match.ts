/**
 * Treffer der globalen Suche (Ctrl+K) für Einträge, die das Frontend selbst kennt (Menüs,
 * Einstellungen, Aktionen). Gross-/Kleinschreibung, Umlaute und Akzente spielen keine Rolle;
 * jedes Wort der Eingabe muss vorkommen (Titel, Bereich oder Suchbegriffe).
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
  if (!words.every((word) => haystack.includes(word))) return 0;
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
