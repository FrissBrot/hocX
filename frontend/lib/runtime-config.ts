declare global {
  interface Window {
    __HOCX_CONFIG__?: {
      mainAppDomain: string | null;
      /** Domain der Benutzer-Doku (TRAEFIK_DOCS_DOMAIN), null = keine Hilfe-Links */
      docsDomain?: string | null;
      /** Öffentliche Statusseite (HOCX_STATUS_PAGE_URL), null = kein Link auf der Update-Seite */
      statusPageUrl?: string | null;
      version: string;
      environment?: string;
      commit?: string | null;
      branch?: string | null;
    };
  }
}

export function getRuntimeConfig() {
  return (
    (typeof window !== "undefined" && window.__HOCX_CONFIG__) || {
      mainAppDomain: null,
      version: "dev"
    }
  );
}
