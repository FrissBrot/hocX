import { NextRequest, NextResponse } from "next/server";

// Auth-Gating lief bisher ausschliesslich in den Server-Components selbst (requireSession()/
// requireAdminSession(), siehe lib/api/server.ts + admin-server.ts) über redirect(). Next.js
// cached das Ergebnis eines Server-Component-Renders (inkl. eines darin ausgelösten redirect())
// aber im client-seitigen Router-Cache - landete dort einmal (z.B. durch einen kurzen
// Backend-Hänger) ein redirect("/login"), wurde dieser bei jeder weiteren Soft-Navigation zu "/"
// aus dem Cache wiederholt, OHNE requireSession() erneut auszuführen - selbst wenn die Session
// laengst wieder gueltig war. Kombiniert mit der Login-Seite, die bei gueltiger Session sofort
// zurueck zu "/" navigiert, ergab das einen Loop, der sich nie von selbst aufloeste (nur ein
// harter Reload leert den Router-Cache).
//
// Middleware läuft dagegen bei JEDEM Request frisch (kein Router-Cache), daher hier die
// eigentliche Weiterleitungs-Entscheidung treffen. Bei einem nicht eindeutigen Ergebnis (Backend
// nicht erreichbar) NICHT umleiten - das übernimmt weiterhin requireSession()/
// requireAdminSession() serverseitig (die dann bewusst einen Error werfen statt umzuleiten, siehe
// dort), damit ein Infrastruktur-Hänger nie mit "nicht eingeloggt" verwechselt wird.
//
// Wichtig: diese Middleware allein hat den Loop NICHT vollständig behoben. Die eigentliche
// Hauptursache war, dass uvicorn unter echter Nebenläufigkeit (mehrere gleichzeitige neue
// TCP-Verbindungen direkt gegen Port 8000, wie sie bei jedem Seitenaufruf mit mehreren
// parallelen serverseitigen Fetches entstehen) nachweislich gelegentlich die falsche Antwort für
// eine gültige Session zurückgab - reproduzierbar mit echten parallelen curl-Requests direkt
// gegen den Container, aber NIE über Traefik/den öffentlichen Domain-Pfad. Der eigentliche Fix
// ist deshalb INTERNAL_API_URL auf die öffentliche Domain zu setzen (siehe .env), sodass auch
// interner Server-Traffic über Traefik läuft statt uvicorn direkt zu treffen. Diese Middleware
// bleibt als zusätzliche Absicherung gegen die (separate, ebenfalls reale) Router-Cache-Replay-
// Problematik oben bestehen.
const internalApiUrl = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function isAuthenticated(cookie: string, sessionPath: string): Promise<boolean | null> {
  try {
    const res = await fetch(`${internalApiUrl}${sessionPath}`, {
      headers: cookie ? { Cookie: cookie } : undefined,
      cache: "no-store"
    });
    if (!res.ok) {
      return null;
    }
    const data = (await res.json()) as { authenticated?: boolean };
    return data.authenticated === true;
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isAdmin = pathname.startsWith("/admin");
  const sessionPath = isAdmin ? "/api/admin/auth/session" : "/api/auth/session";
  const loginPath = isAdmin ? "/admin/login" : "/login";

  const cookie = request.headers.get("cookie") ?? "";
  const authenticated = await isAuthenticated(cookie, sessionPath);

  if (authenticated === false) {
    return NextResponse.redirect(new URL(loginPath, request.url));
  }
  // true oder null (Backend nicht sicher erreichbar) -> Seite normal rendern lassen; die
  // Server-Components validieren ohnehin nochmal und behandeln den Fehlerfall sauber.
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|api$|_next/static|_next/image|favicon\\.ico|login$|login/|admin/login$|admin/login/).*)"]
};
