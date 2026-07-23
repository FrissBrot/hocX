import { cookies, headers } from "next/headers";
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
