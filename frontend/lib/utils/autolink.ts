// Nackte Links in Klartext erkennen - gleiche Regeln wie backend/app/documents/richtext.py
// (find_links): http(s)-URLs, «www.»-Adressen und E-Mail-Adressen; Satzzeichen am Ende gehören
// nicht dazu, eine schliessende Klammer nur, wenn sie eine öffnende im Link schliesst.

export type FoundLink = { from: number; to: number; href: string };

const AUTOLINK = /(\b(?:https?:\/\/|www\.)[^\s<>"]+)|(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b)/g;
const TRAILING = ".,;:!?'\"»«";

function trimLink(candidate: string): string {
  let value = candidate;
  while (value) {
    const last = value[value.length - 1];
    if (TRAILING.includes(last)) {
      value = value.slice(0, -1);
    } else if (last === ")" && (value.match(/\)/g)?.length ?? 0) > (value.match(/\(/g)?.length ?? 0)) {
      value = value.slice(0, -1);
    } else {
      break;
    }
  }
  return value;
}

export function findLinks(text: string): FoundLink[] {
  const links: FoundLink[] = [];
  for (const match of text.matchAll(AUTOLINK)) {
    const start = match.index ?? 0;
    if (match[1]) {
      const value = trimLink(match[1]);
      if (value.length <= "www.".length) continue;
      const href = /^https?:\/\//i.test(value) ? value : `https://${value}`;
      links.push({ from: start, to: start + value.length, href });
    } else if (match[2]) {
      links.push({ from: start, to: start + match[2].length, href: `mailto:${match[2]}` });
    }
  }
  return links;
}
