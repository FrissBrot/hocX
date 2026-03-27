import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { backendFetch } from "@/lib/api/client";
import { SessionInfo } from "@/types/api";

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

export async function requireSession(): Promise<SessionInfo> {
  const session = await backendFetchWithSession<SessionInfo>("/api/auth/session");
  if (!session?.authenticated) {
    redirect("/login");
  }
  return session;
}
