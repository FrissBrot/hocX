import { redirect } from "next/navigation";
import { cache } from "react";

import { backendFetchWithSession } from "@/lib/api/server";
import { AdminSessionInfo } from "@/types/api";

// cache(): Layout der Konsole und Seite fragen die Sitzung im selben Request nur einmal ab.
export const requireAdminSession = cache(async function requireAdminSession(): Promise<AdminSessionInfo> {
  const session = await backendFetchWithSession<AdminSessionInfo>("/api/admin/auth/session");
  if (session === null) {
    // Siehe requireSession() in server.ts: ein nicht erreichbares Backend darf nie wie "nicht
    // eingeloggt" behandelt werden, sonst entsteht derselbe Login-Loop im Admin-Panel.
    throw new Error("Sitzungsprüfung fehlgeschlagen (Backend nicht erreichbar)"); // i18n-ok: Server-Log, error.tsx zeigt eigenen Text
  }
  if (!session.authenticated) {
    redirect("/admin/login");
  }
  return session;
});
