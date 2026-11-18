// Standard für jede Uhrzeit-Eingabe in hocX (verbindlich, siehe design/DESIGN.md Abschnitt 6):
// TimeInput (components/ui/time-input.tsx) nutzt diesen Parser, eigene Zeitfelder oder eigene
// Zeit-Regexe gibt es nicht. Der Parser versteht die üblichen Schreibweisen und liefert immer
// «HH:MM» (24 h); das Feld zeigt den korrigierten Wert beim Verlassen bzw. mit Enter.
//
//   9 → 09:00 · 930 / 9.30 / 9,30 / 9h30 / 9 30 → 09:30 · 1130 / 11:30 → 11:30 · 230 → 02:30
//   11:5 → 11:05 · 14 Uhr / 14h → 14:00 · 13:30:00 → 13:30 · 7pm / 7:30 p.m. → 19:00 / 19:30
//   12am → 00:00 · ungültig (25, 1260, 9:75, abc) → null

const MERIDIEM = /\s*([ap])\.?\s*m\.?$/;

/** «HH:MM» aus einer frei getippten Uhrzeit; null, wenn sie keine gültige Uhrzeit ist. */
export function parseTimeInputValue(raw: string): string | null {
  let text = String(raw ?? "").trim().toLowerCase().replace(/\s+/g, " ").replace(/\s*uhr$/, "");
  if (!text) return null;
  let meridiem: "am" | "pm" | null = null;
  const meridiemMatch = MERIDIEM.exec(text);
  if (meridiemMatch) {
    meridiem = meridiemMatch[1] === "a" ? "am" : "pm";
    text = text.slice(0, meridiemMatch.index).trim();
  }
  text = text.replace(/\s*h$/, "");

  let hours: number;
  let minutes: number;
  // Mit Trennzeichen (: . , h Leerzeichen -); Sekunden werden ignoriert
  const separated = /^(\d{1,2})\s*[:.,h -]\s*(\d{1,2})(?:\s*[:.]\s*\d{1,2})?$/.exec(text);
  if (separated) {
    hours = Number(separated[1]);
    minutes = Number(separated[2]);
  } else if (/^\d{1,4}$/.test(text)) {
    // Nur Ziffern: 1–2 Stellen = Stunde, 3 Stellen = H + MM, 4 Stellen = HH + MM
    if (text.length <= 2) {
      hours = Number(text);
      minutes = 0;
    } else if (text.length === 3) {
      hours = Number(text.slice(0, 1));
      minutes = Number(text.slice(1));
    } else {
      hours = Number(text.slice(0, 2));
      minutes = Number(text.slice(2));
    }
  } else {
    return null;
  }

  if (meridiem) {
    if (hours < 1 || hours > 12) return null;
    hours = (hours % 12) + (meridiem === "pm" ? 12 : 0);
  }
  if (hours > 23 || minutes > 59) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/** Gespeicherte Zeit («HH:MM:SS» aus der API oder «HH:MM») für Anzeige und TimeInput als «HH:MM». */
export function formatTimeValue(value: string | null | undefined): string {
  return value ? parseTimeInputValue(String(value)) ?? "" : "";
}
