import { redirect } from "next/navigation";

import { backendFetchWithSession } from "@/lib/api/server";
import { AdminSessionInfo } from "@/types/api";

export async function requireAdminSession(): Promise<AdminSessionInfo> {
  const session = await backendFetchWithSession<AdminSessionInfo>("/api/admin/auth/session");
  if (!session?.authenticated) {
    redirect("/admin/login");
  }
  return session;
}
