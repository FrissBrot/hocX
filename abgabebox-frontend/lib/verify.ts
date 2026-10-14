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
};

export type VerifyOutcome =
  | { kind: "not_found" }
  | {
      kind: "original";
      result: VerifyResponse;
      // Datei echt, gehört aber zu einem anderen Dokument als der gescannte QR-Code
      otherDocument: boolean;
      newerVersion: string | null;
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
    identity,
  };
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
    throw new Error(`verify ${response.status}`);
  }
  return (await response.json()) as VerifyResponse;
}
