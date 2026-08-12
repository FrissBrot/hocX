const APP_TIME_ZONE = "Europe/Zurich";

// Minimal, eigenständige Portierung von formatDate() aus dem Haupt-hocX-Frontend
// (frontend/lib/utils/format.ts). Bewusst ohne Abhängigkeit zum Hauptfrontend,
// da abgabebox-frontend ein separates Deployment ist. Formatiert reine ISO-Datumsangaben
// (YYYY-MM-DD, wie sie das Abgabebox-Backend für window_start/window_end liefert) sowie
// volle ISO-Zeitstempel auf das im Rest von hocX übliche Format DD.MM.YYYY.
export function formatDate(input: string | null | undefined): string {
  if (!input) {
    return "";
  }

  const [datePart] = input.split("T");
  const [year, month, day] = datePart.split("-");
  if (year && month && day) {
    return `${day}.${month}.${year}`;
  }

  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) {
    return input;
  }

  return new Intl.DateTimeFormat("de-CH", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: APP_TIME_ZONE,
  }).format(parsed);
}
