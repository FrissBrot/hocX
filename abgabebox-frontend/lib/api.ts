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

// Browser-seitig (Upload-Formular) wird die oeffentliche Domain direkt angesprochen.
export function publicApiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_ABGABEBOX_API_URL ?? "";
  return `${base}${path}`;
}
