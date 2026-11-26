import { headers } from "next/headers";

// Pfade der oeffentlichen Website. Auf der Website-Domain (TRAEFIK_WEBSITE_DOMAIN) schreibt
// proxy.ts jeden Pfad nach /website<pfad> um, dort heissen die Seiten also /privacy und /terms.
// Ohne Website-Domain (Entwicklung, E2E) sind sie direkt unter /website/... erreichbar. Links
// zwischen den Website-Seiten laufen deshalb ueber websiteBasePath(), damit sie in beiden
// Faellen auf der Website bleiben (ein Link auf /privacy ausserhalb der Website-Domain landete
// sonst in der App und dort auf /login).
export const WEBSITE_PAGES = {
  home: "",
  privacy: "/privacy",
  terms: "/terms",
} as const;

export type WebsitePage = keyof typeof WEBSITE_PAGES;

export function websiteHref(base: string, page: WebsitePage, anchor?: string): string {
  const path = `${base}${WEBSITE_PAGES[page]}` || "/";
  return anchor ? `${path}#${anchor}` : path;
}

// "" auf der Website-Domain, sonst "/website" (Host-Vergleich wie in proxy.ts).
export async function websiteBasePath(): Promise<string> {
  const websiteDomain = process.env.TRAEFIK_WEBSITE_DOMAIN?.trim().toLowerCase();
  if (!websiteDomain) {
    return "/website";
  }
  const host = (await headers()).get("host")?.split(":")[0]?.toLowerCase();
  return host === websiteDomain ? "" : "/website";
}
