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

// Nur an ein internes Ziel weiterreichen (Review L2): Container-Name ohne Punkt, localhost oder
// Loopback - nie an eine öffentliche Domain. scripts/deploy.sh erzwingt das für INTERNAL_API_URL.
export function isInternalApiTarget(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || (host !== "" && !host.includes("."));
  } catch {
    return false;
  }
}

// Rolle dieses Next-Prozesses (Review M3): "public" liefert nie /admin aus und reicht den
// Gate-Header nie weiter; "admin" ist der eigene Dienst admin-frontend hinter dem Admin-Entrypoint.
// Ohne Angabe (Entwicklung, E2E) entscheidet wie bisher der Host.
export type FrontendRole = "public" | "admin" | undefined;

export function frontendRole(value = process.env.HOCX_FRONTEND_ROLE): FrontendRole {
  return value === "public" || value === "admin" ? value : undefined;
}

// Header für einen serverseitigen Aufruf der Admin-API: Gate-Header und ursprünglicher Host (als
// X-Forwarded-Host, Nodes fetch verwirft einen eigenen Host-Header). Fehlt der Gate-Header (kein
// Request über den Admin-Entrypoint), ist das Ziel nicht intern oder ist dies das öffentliche
// Frontend, wird nichts weitergereicht - das Backend lehnt dann ab.
export function adminGateForwardHeaders(
  incoming: Pick<Headers, "get">,
  targetUrl: string,
  role: FrontendRole = frontendRole()
): Record<string, string> {
  const gate = incoming.get(ADMIN_GATE_HEADER);
  if (!gate || role === "public" || !isInternalApiTarget(targetUrl)) {
    return {};
  }
  const forwarded: Record<string, string> = { [ADMIN_GATE_HEADER]: gate };
  const host = incoming.get("host") ?? incoming.get("x-forwarded-host");
  if (host) {
    forwarded["x-forwarded-host"] = host;
  }
  return forwarded;
}
