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
  // `||` statt `??`: docker-compose reicht nicht gesetzte Variablen als "" durch
  // (HOCX_APP_URL: ${HOCX_APP_URL:-}) - ein leerer Wert soll auf TRAEFIK_DOMAIN zurueckfallen.
  return normalizeUrl(process.env.HOCX_APP_URL?.trim() || process.env.TRAEFIK_DOMAIN?.trim() || null);
}
