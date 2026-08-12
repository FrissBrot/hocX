export type AssignmentPublic = {
  public_slug: string;
  title: string;
  description: string | null;
};

export type AssignmentDetailPublic = {
  public_slug: string;
  title: string;
  description: string | null;
  allowed_file_types: string[];
  max_files_per_element: number;
  max_file_size_mb: number;
};

export type ElementPublic = {
  element_ref: string;
  label: string;
  window_start: string | null;
  window_end: string | null;
};

// Deliberately not shared with frontend/lib/api/server.ts's backendFetch: this is a
// separately deployed Next.js app (own package.json/Dockerfile, see audit finding
// E-Niedrig-4) with genuinely simpler requirements - these are unauthenticated public
// endpoints, so there's no session cookie to forward and no login-loop retry logic
// needed (see backendFetch's own comment for why that retry exists there). Pulling both
// into a shared package would need a monorepo workspace for two intentionally isolated
// services; not worth it for ~6 lines that differ in what they actually need to do.
async function fetchJson<T>(url: string): Promise<T | null> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as T;
}

// Server-side (SSR) Aufrufe laufen ueber das interne Docker-Netzwerk, analog zu
// INTERNAL_API_URL im Haupt-hocX-Frontend.
const internalBase = process.env.INTERNAL_ABGABEBOX_API_URL ?? "http://abgabebox-backend:8000";

export function listAssignments(tenantSlug: string) {
  return fetchJson<AssignmentPublic[]>(`${internalBase}/api/public/${tenantSlug}/assignments`);
}

export function getAssignmentDetail(tenantSlug: string, assignmentSlug: string) {
  return fetchJson<AssignmentDetailPublic>(`${internalBase}/api/public/${tenantSlug}/assignments/${assignmentSlug}`);
}

export function listElements(tenantSlug: string, assignmentSlug: string) {
  return fetchJson<ElementPublic[]>(`${internalBase}/api/public/${tenantSlug}/assignments/${assignmentSlug}/elements`);
}

export function getElement(tenantSlug: string, assignmentSlug: string, elementRef: string) {
  return listElements(tenantSlug, assignmentSlug).then(
    (elements) => elements?.find((element) => element.element_ref === elementRef) ?? null
  );
}

// Browser-seitig (Upload-Formular) wird immer same-origin (relativer Pfad) angesprochen, damit
// das auf jeder Domain (Standard- oder Mandanten-Custom-Domain) automatisch korrekt aufgeloest wird.
export function publicApiUrl(path: string): string {
  return path;
}
