import type { CalendarFeedKind } from "@/types/api";

// Kalender-Abos ("Verknuepfungen"): Hilfsfunktionen fuer die Abo-Links. Das Backend liefert nur
// den relativen Pfad (/api/public/calendar/<token>.ics) - /api liegt immer auf derselben Origin
// wie das Frontend (Traefik bzw. Next-Rewrite), daher wird hier die eigene Origin vorangestellt.

export function calendarFeedUrl(path: string, origin: string): string {
  return `${origin}${path}`;
}

/** webcal:// oeffnet auf iPhone/iPad/Mac direkt den "Kalender abonnieren"-Dialog. */
export function appleSubscribeUrl(path: string, origin: string): string {
  return calendarFeedUrl(path, origin).replace(/^https?:\/\//, "webcal://");
}

/** Google Kalender: "Per URL hinzufuegen" mit vorausgefuellter Adresse. */
export function googleSubscribeUrl(path: string, origin: string): string {
  return `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(appleSubscribeUrl(path, origin))}`;
}

/** Spiegelt calendar_feed_service.can_subscribe: Termine nur fuer writer/admin (wie die
 * Termine-Seite selbst), Todos fuer alle Rollen. */
export function canSubscribeCalendar(role: string | null | undefined, kind: CalendarFeedKind): boolean {
  if (kind === "events") return role === "admin" || role === "writer";
  return role === "admin" || role === "writer" || role === "kassier" || role === "reader";
}

export const CONNECTIONS_HREF = "/connections";
