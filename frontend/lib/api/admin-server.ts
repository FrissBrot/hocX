import { redirect } from "next/navigation";

import { backendFetchWithSession } from "@/lib/api/server";
import { AdminSessionInfo } from "@/types/api";

export async function requireAdminSession(): Promise<AdminSessionInfo> {
  const session = await backendFetchWithSession<AdminSessionInfo>("/api/admin/auth/session");
  if (session === null) {
    // Siehe requireSession() in server.ts: ein nicht erreichbares Backend darf nie wie "nicht
    // eingeloggt" behandelt werden, sonst entsteht derselbe Login-Loop im Admin-Panel.
    throw new Error("Sitzungsprüfung fehlgeschlagen (Backend nicht erreichbar)");
  }
  if (!session.authenticated) {
    redirect("/admin/login");
  }
  return session;
}
