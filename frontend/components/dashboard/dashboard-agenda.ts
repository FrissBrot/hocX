// Agenda der Startseite (Dashboard v2): Termine, Sitzungen und Abgabefristen nach Wochen
// gruppiert ("Diese Woche", "Nächste Woche", danach je Monat). Reine Logik ohne React, Texte
// übersetzt die Komponente (siehe dashboard-agenda.test.ts).

export type AgendaKind = "session" | "event" | "deadline";

export type AgendaItem = {
  id: string;
  date: string;
  title: string;
  sub: string;
  kind: AgendaKind;
  href: string | null;
};

export type AgendaGroup = { key: string; label: { type: "thisWeek" | "nextWeek" } | { type: "month"; month: string }; items: AgendaItem[] };

function utc(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Montag der Woche (ISO, Woche beginnt am Montag) als Tageszahl seit 1970. */
function mondayOf(iso: string): number {
  const day = utc(iso) / 86_400_000;
  const weekday = (new Date(utc(iso)).getUTCDay() + 6) % 7;
  return day - weekday;
}

export function groupAgenda(items: AgendaItem[], todayIso: string, limit: number): AgendaGroup[] {
  const thisMonday = mondayOf(todayIso);
  const sorted = [...items].filter((item) => item.date.slice(0, 10) >= todayIso).sort((a, b) => a.date.localeCompare(b.date) || a.title.localeCompare(b.title)).slice(0, limit);
  const groups: AgendaGroup[] = [];
  for (const item of sorted) {
    const weeks = Math.floor((mondayOf(item.date) - thisMonday) / 7);
    const label: AgendaGroup["label"] = weeks === 0 ? { type: "thisWeek" } : weeks === 1 ? { type: "nextWeek" } : { type: "month", month: item.date.slice(0, 7) };
    const key = label.type === "month" ? `month:${label.month}` : label.type;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, label, items: [item] });
  }
  return groups;
}
