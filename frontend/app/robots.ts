import type { MetadataRoute } from "next";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

export default async function robots(): Promise<MetadataRoute.Robots> {
  // Die oeffentliche Website (TRAEFIK_WEBSITE_DOMAIN, gleicher Frontend-Service) soll gefunden
  // werden; App- und Admin-Domain bleiben fuer Suchmaschinen gesperrt.
  const websiteDomain = process.env.TRAEFIK_WEBSITE_DOMAIN;
  const host = (await headers()).get("host")?.split(":")[0];
  if (websiteDomain && host === websiteDomain) {
    return { rules: { userAgent: "*", allow: "/" } };
  }
  return {
    rules: {
      userAgent: "*",
      disallow: "/",
    },
  };
}
