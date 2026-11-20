// Plattform-Admin nur über die Admin-Domain (Auth-Audit SEC-AUTH-001, Defense in Depth).
//
// Traefik setzt an jedem Router des Admin-Entrypoints (adminsecure, nur über OpenZiti erreichbar)
// den Header X-Hocx-Admin-Gate auf ein Secret und entfernt ihn auf allen öffentlichen Entrypoints.
// Das Backend nimmt /api/admin nur mit diesem Header und auf der Admin-Domain an
// (backend/app/core/admin_gate.py). Der Next.js-Server ruft die Admin-API serverseitig direkt über
// INTERNAL_API_URL auf (nicht über Traefik) - er reicht dafür den Gate-Header und den Host weiter,
// die er selbst von Traefik bekommen hat. Das Secret kennt das Frontend nicht.

export const ADMIN_GATE_HEADER = "x-hocx-admin-gate";

export function isAdminPagePath(pathname: string): boolean {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

export function isAdminApiPath(path: string): boolean {
  return path === "/api/admin" || path.startsWith("/api/admin/") || path.startsWith("/api/admin?");
}

export function normalizeHost(host: string | null | undefined): string {
  return (host ?? "").split(":")[0].trim().toLowerCase().replace(/\.$/, "");
}

// Darf eine Admin-Seite auf diesem Host ausgeliefert werden? Ohne konfigurierte Admin-Domain
// (Entwicklung, E2E-Stack) überall, sonst nur auf ihr.
export function adminAllowedOnHost(host: string | null | undefined, adminDomain: string | undefined): boolean {
  const expected = normalizeHost(adminDomain);
  return !expected || normalizeHost(host) === expected;
}

// Header für einen serverseitigen Aufruf der Admin-API: Gate-Header und ursprünglicher Host (als
// X-Forwarded-Host, Nodes fetch verwirft einen eigenen Host-Header). Fehlt der Gate-Header (kein
// Request über den Admin-Entrypoint), wird auch nichts weitergereicht - das Backend lehnt dann ab.
export function adminGateForwardHeaders(incoming: Pick<Headers, "get">): Record<string, string> {
  const gate = incoming.get(ADMIN_GATE_HEADER);
  if (!gate) {
    return {};
  }
  const forwarded: Record<string, string> = { [ADMIN_GATE_HEADER]: gate };
  const host = incoming.get("host") ?? incoming.get("x-forwarded-host");
  if (host) {
    forwarded["x-forwarded-host"] = host;
  }
  return forwarded;
}
