// Markdown der Termintexte (Beschreibung, Programm, Spezial-Texte) als einzeiliger Klartext für
// Listen, Tabellenzellen und Vorschauen, wo kein Rich-Text-Editor gerendert werden soll. Die
// vollständige Darstellung übernimmt RichTextEditor (Formular, readOnly) bzw. das PDF.

/** Markdown in kurzen Klartext: Formatierung, Listenzeichen, Überschriften und Links entfernt,
 * Absätze und Zeilen mit « · » verbunden. */
export function markdownToPlainText(markdown: string | null | undefined): string {
  const source = String(markdown ?? "").replace(/\r\n/g, "\n");
  if (!source.trim()) return "";
  const lines = source
    .split("\n")
    .map((line) =>
      line
        .replace(/^\s{0,3}#{1,6}\s+/, "")
        .replace(/^\s*>\s?/, "")
        .replace(/^\s*(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?/, "")
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/(\*\*|__)(.+?)\1/g, "$2")
        .replace(/(\*|_)(.+?)\1/g, "$2")
        .replace(/~~(.+?)~~/g, "$1")
        .replace(/`([^`]*)`/g, "$1")
        .replace(/\\([\\`*_{}[\]()#+\-.!>~|])/g, "$1")
        .replace(/\\$/, "")
        .trim()
    )
    .filter(Boolean);
  return lines.join(" · ");
}

