import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { backendFetch } from "@/lib/api/client";
import { SessionInfo, TenantSummary } from "@/types/api";

export async function cookieHeader(): Promise<string> {
  const cookieStore = await cookies();
  return cookieStore
    .getAll()
    .map((item) => `${item.name}=${item.value}`)
    .join("; ");
}

export async function backendFetchWithSession<T>(path: string): Promise<T | null> {
  const cookie = await cookieHeader();
  return backendFetch<T>(path, {
    headers: cookie ? { Cookie: cookie } : undefined
  });
}

// Lädt eine skip/limit-paginierte Liste vollständig. Für Daten, die clientseitig gefiltert
// werden und dabei mit dem (ungekürzten) PDF-Export übereinstimmen müssen, z. B. Termine im
// Protokolleditor - der Standard-limit von /api/events (100) hat dort ältere Termine abgeschnitten.
export async function backendFetchAllPagesWithSession<T>(path: string, pageSize = 500): Promise<T[]> {
  const separator = path.includes("?") ? "&" : "?";
  const items: T[] = [];
  for (let skip = 0; ; skip += pageSize) {
    const page = await backendFetchWithSession<T[]>(`${path}${separator}skip=${skip}&limit=${pageSize}`);
    if (!page) break;
    items.push(...page);
    if (page.length < pageSize) break;
  }
  return items;
}

export async function requireSession(): Promise<SessionInfo> {
  const session = await backendFetchWithSession<SessionInfo>("/api/auth/session");
  if (session === null) {
    // Volle Wartung: das Backend antwortet mit 503 - Wartungsansicht statt Fehlerseite.
    const maintenance = await backendFetch<{ active: boolean }>("/api/public/maintenance-status");
    if (maintenance?.active) {
      redirect("/maintenance");
    }
    // backendFetch() konnte das Backend gar nicht erreichen (Netzwerkfehler/Timeout, auch nach
    // eigenem Retry) - das ist NICHT dasselbe wie "nicht eingeloggt" und darf niemals zu /login
    // umleiten: der Browser hat die Session oft schon selbst als gültig geprüft und würde auf
    // /login sofort wieder zurück hierher springen (siehe proxy.ts (ehemals middleware.ts) für den Haupt-Fix des
    // eigentlichen Login-Loops - hier geht es nur um den verbleibenden Ambiguitäts-Fall). Ein
    // regulärer Error lässt stattdessen die error.tsx-Boundary greifen, die KEINE automatische
    // Weiterleitung auslöst.
    throw new Error("Sitzungsprüfung fehlgeschlagen (Backend nicht erreichbar)");
  }
  if (!session.authenticated) {
    // Login rendert nie auf einer Mandanten-Custom-Domain — von dort muss serverseitig zur
    // Hauptdomain umgeleitet werden, sonst gäbe es dort keine Login-Seite zu zeigen.
    const mainDomain = process.env.TRAEFIK_DOMAIN;
    const host = (await headers()).get("host");
    if (mainDomain && host && host !== mainDomain) {
      // `from` lässt die Login-Seite den Mandanten anhand der Domain automatisch waehlen,
      // statt den Nutzer manuell eine Organisation auswaehlen zu lassen.
      redirect(`https://${mainDomain}/login?from=${encodeURIComponent(host)}`);
    }
    redirect("/login");
  }
  return session;
}

// Shared by the /tenant-settings/* pages (Allgemein, Domains, Abo & Nutzung each get their own
// route): resolves which tenant to show from an optional `?tenantId=` override, falling back to
// the session's current tenant. `/api/tenants` is already scoped to tenants the current user
// administers.
export async function resolveManageableTenant(session: SessionInfo, tenantId: string | undefined): Promise<TenantSummary> {
  const manageableTenants = await backendFetchWithSession<TenantSummary[]>("/api/tenants");
  if (!manageableTenants || manageableTenants.length === 0) {
    redirect("/");
  }
  const requestedId = tenantId ? tenantId : session.current_tenant?.id;
  return manageableTenants.find((t) => t.id === requestedId) ?? manageableTenants[0];
}
