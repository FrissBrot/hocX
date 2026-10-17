// Echtheitsprüfung von PDFs aus hocX (Seite /verify). Die Datei verlässt den Browser nie: der
// SHA-256 wird hier mit der Web Crypto API berechnet, an das Abgabebox-Backend geht nur der Hash
// (und optional die Dokument-ID aus dem QR-Code).

export type VerifyResponse = {
  found: boolean;
  document_id?: string;
  document_id_matches?: boolean;
  document_type?: string;
  title?: string;
  status_code?: string;
  version_label?: string;
  created_at?: string;
  is_superseded?: boolean;
  latest_version_label?: string;
  tenant_name?: string;
  tenant_public_id?: string;
  tenant_has_logo?: boolean;
  organization_verified?: boolean;
  import_unverified?: boolean;
  title_overridden?: boolean;
  // Prüf-Domain des ausstellenden Mandanten (z. B. verify.verein.ch)
  verify_domain?: string;
};

// Kopf der Prüfseite unter einer Mandanten-Prüf-Domain (GET /api/public/verify/site). tenant_*
// fehlen auf der zentralen Prüfseite und auf Domains, die keine aktive Prüf-Domain sind.
export type VerifySite = {
  domain?: string;
  tenant_name?: string;
  tenant_public_id?: string;
  tenant_has_logo?: boolean;
  organization_verified?: boolean;
  central_verify_url: string;
};

export type VerifyRedirect =
  // Prüfseite des ausstellenden Mandanten
  | { kind: "tenant"; domain: string; url: string }
  // Dokument eines anderen Mandanten ohne eigene Prüf-Domain: zurück zur Prüfseite von hocX
  | { kind: "central"; url: string };

export type VerifyOutcome =
  | { kind: "not_found" }
  | {
      kind: "original";
      result: VerifyResponse;
      // Datei echt, gehört aber zu einem anderen Dokument als der gescannte QR-Code
      otherDocument: boolean;
      newerVersion: string | null;
      // Eintrag aus einem Datenimport, beim Import nicht mit der Originaldatei abgeglichen
      importUnverified: boolean;
      // Titel beim Export abweichend vom Protokoll gesetzt (STUDIO-007)
      titleOverridden: boolean;
      identity: "verified" | "named" | "anonymous";
    };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseDocumentId(value: string | string[] | null | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && UUID_PATTERN.test(raw.trim()) ? raw.trim().toLowerCase() : null;
}

// Kurz-ID wie im PDF: letzte 8 Hex-Zeichen, gruppiert («7F3A-91C2»)
export function shortDocumentId(documentId: string): string {
  const tail = documentId.replace(/-/g, "").slice(-8).toUpperCase();
  return `${tail.slice(0, 4)}-${tail.slice(4)}`;
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function classifyResult(result: VerifyResponse): VerifyOutcome {
  if (!result.found) {
    return { kind: "not_found" };
  }
  const identity = result.tenant_name ? (result.organization_verified ? "verified" : "named") : "anonymous";
  return {
    kind: "original",
    result,
    otherDocument: result.document_id_matches === false,
    newerVersion: result.is_superseded ? result.latest_version_label ?? null : null,
    importUnverified: result.import_unverified === true,
    titleOverridden: result.title_overridden === true,
    identity,
  };
}

// Fremdes Dokument auf der Prüfseite eines Mandanten? Nur Dokumente des Mandanten hinter der
// Prüf-Domain tragen deren Stufe «Prüf-Domain verifiziert».
export function isSiteDocument(result: VerifyResponse, site: VerifySite | null): boolean {
  return Boolean(site?.tenant_public_id && result.tenant_public_id && site.tenant_public_id === result.tenant_public_id);
}

// Der Hash reist bei der Weiterleitung im Fragment (#sha256=...): der Browser schickt ihn nie an
// einen Server, die Zielseite prüft damit sofort, ohne die Datei erneut zu verlangen.
const HASH_FRAGMENT = /^#?sha256=([0-9a-f]{64})$/;

export function parseHashFragment(fragment: string | null | undefined): string | null {
  const match = HASH_FRAGMENT.exec((fragment ?? "").trim().toLowerCase());
  return match ? match[1] : null;
}

function withCheck(base: string, documentId: string | null, sha256: string): string {
  const url = new URL(base);
  if (documentId) url.searchParams.set("id", documentId);
  url.hash = `sha256=${sha256}`;
  return url.toString();
}

// Wohin nach einem Treffer weitergeleitet wird - null, wenn das Dokument hierher gehört. Endet
// nie in einer Schleife: die Prüfseite des Mandanten leitet dessen eigene Dokumente nicht weiter,
// die zentrale Seite (keine Prüf-Domain) nur zu einem Mandanten mit verify_domain.
export function redirectTarget(
  result: VerifyResponse,
  options: { currentHost: string; site: VerifySite | null; documentId: string | null; sha256: string }
): VerifyRedirect | null {
  if (!result.found) return null;
  const { currentHost, site, documentId, sha256 } = options;
  const host = currentHost.toLowerCase();
  const domain = result.verify_domain?.toLowerCase();
  if (domain && domain !== host) {
    return { kind: "tenant", domain, url: withCheck(`https://${domain}/verify`, documentId, sha256) };
  }
  if (site?.tenant_public_id && !isSiteDocument(result, site) && !domain) {
    return { kind: "central", url: withCheck(site.central_verify_url, documentId, sha256) };
  }
  return null;
}

// Same-origin: funktioniert auf der Plattform-Domain und auf Mandanten-Abgabebox-Domains.
export async function verifyHash(sha256: string, documentId: string | null): Promise<VerifyResponse> {
  const response = await fetch("/api/public/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    cache: "no-store",
    body: JSON.stringify(documentId ? { sha256, document_id: documentId } : { sha256 }),
  });
  if (!response.ok) {
    throw new Error(`verify ${response.status}`); // i18n-ok: technischer Fehler, verify-check.tsx zeigt eine übersetzte Meldung
  }
  return (await response.json()) as VerifyResponse;
}
