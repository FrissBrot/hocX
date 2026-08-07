export type SiteVariant = "app" | "marketing";

function normalizeUrl(raw: string | null | undefined): string | null {
  if (!raw) {
    return null;
  }

  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }

  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

export function getSiteVariant(): SiteVariant {
  return process.env.HOCX_SITE_VARIANT === "marketing" ? "marketing" : "app";
}

export function isMarketingVariant(): boolean {
  return getSiteVariant() === "marketing";
}

export function getMainAppUrl(): string | null {
  return normalizeUrl(process.env.HOCX_APP_URL ?? process.env.TRAEFIK_DOMAIN ?? null);
}

export function getMarketingUrl(): string | null {
  return normalizeUrl(process.env.HOCX_MARKETING_URL ?? process.env.TRAEFIK_WEB_DOMAIN ?? null);
}

export function getDocsUrl(): string | null {
  return normalizeUrl(process.env.HOCX_DOCS_URL ?? process.env.TRAEFIK_DOCS_DOMAIN ?? null);
}

export function getCurrentBaseUrl(): string | null {
  return isMarketingVariant() ? getMarketingUrl() ?? getMainAppUrl() : getMainAppUrl() ?? getMarketingUrl();
}
