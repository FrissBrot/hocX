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

export function getMainAppUrl(): string | null {
  return normalizeUrl(process.env.HOCX_APP_URL ?? process.env.TRAEFIK_DOMAIN ?? null);
}
