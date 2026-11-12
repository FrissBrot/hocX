declare global {
  interface Window {
    __HOCX_CONFIG__?: {
      mainAppDomain: string | null;
      /** Domain der Benutzer-Doku (TRAEFIK_DOCS_DOMAIN), null = keine Hilfe-Links */
      docsDomain?: string | null;
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
