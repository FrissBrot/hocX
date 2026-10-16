// Typen und Aufrufe des Document Studio (Vorlagen, Brand-Profile, Assets, Komponenten,
// Zuweisungen, Katalog) und des Export Center (Export, Vorschau, Zusatzformate, Historie).
// Schnittstelle siehe backend/app/api/routes/document_studio.py und documents.py.

import { ApiError, browserApiFetch } from "@/lib/api/client";
import type { BrandTokens, TemplateContent, TemplateNode } from "@/lib/documents/layout";

export const DOCUMENT_TIMEOUT_MS = 120_000;

// ── Katalog ─────────────────────────────────────────────────────────────────

export type JsonSchema = {
  type?: string;
  format?: string;
  enum?: (string | number)[];
  const?: string | number;
  default?: unknown;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  maxItems?: number;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  "x-source"?: string;
  "x-widget"?: string;
};

export type EditorMode = "simple" | "advanced" | "expert";

export type NodeTypeInfo = {
  category: "layout" | "content" | "document" | "data";
  mode: EditorMode;
  groups: string[];
  icon: string;
  container: boolean;
  master_only: boolean;
};

export type LibraryEntry = {
  key: string;
  group: string;
  mode: EditorMode;
  node: Partial<TemplateNode> & { type: string };
  master_only: boolean;
  access: "reader" | "writer" | "finance";
  needs_protocol: boolean;
};

export type DataComponentInfo = {
  type: string;
  group: string;
  access: "reader" | "writer" | "finance";
  needs_protocol: boolean;
  params_schema: JsonSchema;
};

export type BindingInfo = {
  path: string;
  type: "text" | "date" | "number" | "amount" | "percent" | "image" | "bool" | "list";
  group: string;
  access: "reader" | "writer" | "finance";
  needs_protocol: boolean;
  item_fields: { key: string; type: string }[];
};

export type DocumentTypeInfo = { key: string; category: string; needs_protocol: boolean; formats: ("csv" | "xlsx" | "ics" | "markdown")[] };

export type StudioCatalog = {
  node_types: Record<string, NodeTypeInfo>;
  library: LibraryEntry[];
  data_components: DataComponentInfo[];
  bindings: BindingInfo[];
  document_types: DocumentTypeInfo[];
  categories: string[];
  modes: EditorMode[];
  color_references: string[];
  fonts: string[];
  brand_presets: string[];
};

export type Capabilities = {
  export: boolean;
  view_templates: boolean;
  edit_templates: boolean;
  publish_templates: boolean;
  manage_brand: boolean;
  finance_data: boolean;
  personal_data: boolean;
  unmark_drafts?: boolean;
};

// ── Vorlagen ────────────────────────────────────────────────────────────────

export type Diagnostic = { node_id: string | null; severity: "error" | "warning"; code: string; detail: string };

export type RevisionInfo = {
  id: string;
  revision_no: number;
  status: "draft" | "published" | "superseded";
  lock_version: number;
  brand_mode: "follow" | "pinned";
  schema_version: number;
  note: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  created_by_name: string | null;
  published_by_name: string | null;
};

export type DocumentTemplateInfo = {
  id: string;
  name: string;
  description: string | null;
  document_type: string;
  variant: string | null;
  category: string;
  origin: "system" | "tenant" | "copy";
  system_key: string | null;
  source_system_key: string | null;
  status: "active" | "archived";
  editable: boolean;
  is_default: boolean;
  brand_id: string | null;
  published_revision: RevisionInfo | null;
  draft_revision: RevisionInfo | null;
  created_at: string;
  updated_at: string;
};

export type DocumentTemplateDetail = DocumentTemplateInfo & {
  content: TemplateContent;
  working_revision_id: string | null;
  diagnostics: Diagnostic[];
};

export type RevisionDiff = {
  nodes: { change: "added" | "removed" | "modified" | "moved"; node_id: string; type: string; name: string | null; area: string; fields?: string[] }[];
  settings: string[];
  masters: string[];
};

export type Assignment = {
  document_type: string;
  protocol_template_id: string | null;
  protocol_template_name: string | null;
  template_id: string | null;
  brand_id: string | null;
};

// ── Brand, Assets, Komponenten ──────────────────────────────────────────────

export type Brand = {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  archived: boolean;
  revision: number;
  lock_version: number;
  tokens: BrandTokens;
  updated_at: string;
};

export type BrandRevision = { id: string; revision: number; note: string | null; created_at: string; created_by_name: string | null };

export type DocumentAsset = {
  id: string;
  kind: "image" | "font";
  category: "logo" | "letterhead" | "background" | "watermark" | "graphic" | "image" | "font";
  name: string;
  original_name: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  width_px: number | null;
  height_px: number | null;
  font_family: string | null;
  content_url: string;
  created_at: string;
};

export type AssetReference = { kind: "brand" | "template" | "component"; id: string; name: string };

export type ReusableComponent = { id: string; name: string; description: string | null; category: string; lock_version: number; node: TemplateNode; updated_at: string };

// ── Export ──────────────────────────────────────────────────────────────────

export type ExportOptions = { title?: string | null; subtitle?: string | null; watermark?: "auto" | "on" | "off" };

export type DocumentRequest = {
  document_type?: string | null;
  protocol_id?: string | null;
  template_id?: string | null;
  revision_id?: string | null;
  content?: TemplateContent | null;
  brand_id?: string | null;
  brand_tokens?: BrandTokens | null;
  params?: Record<string, unknown>;
  options?: ExportOptions;
  language?: string | null;
  data_mode?: "data" | "sample";
};

export type DocumentExport = {
  id: string;
  document_type: string;
  title: string | null;
  version_label: string | null;
  short_id: string;
  verify_url: string;
  language: string | null;
  template_id: string | null;
  template_name: string | null;
  template_system_key: string | null;
  template_revision: number | null;
  content_hash: string | null;
  design_hash: string | null;
  generated_file_id: string | null;
  content_url: string | null;
  created_at: string;
};

export type PreviewResult = {
  pages: string[];
  page_count: number;
  diagnostics: Diagnostic[];
  template_id: string | null;
  template_source: string | null;
  design_hash: string | null;
};

export type SourceOption = { id: string; label: string; detail?: string | null };

// ── Aufrufe ─────────────────────────────────────────────────────────────────

const json = (body: unknown, method = "POST"): RequestInit => ({ method, body: JSON.stringify(body) });

export const studioApi = {
  capabilities: () => browserApiFetch<Capabilities>("/api/document-studio/capabilities"),
  catalog: () => browserApiFetch<StudioCatalog>("/api/document-studio/catalog"),

  listTemplates: (params: { documentType?: string; includeArchived?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.documentType) query.set("document_type", params.documentType);
    if (params.includeArchived) query.set("include_archived", "true");
    const suffix = query.toString() ? `?${query}` : "";
    return browserApiFetch<DocumentTemplateInfo[]>(`/api/document-templates${suffix}`);
  },
  getTemplate: (id: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}`),
  createTemplate: (body: { name: string; document_type: string; description?: string | null; from_template_id?: string | null; content?: TemplateContent | null }) =>
    browserApiFetch<DocumentTemplateDetail>("/api/document-templates", json(body)),
  updateTemplate: (id: string, body: { name?: string; description?: string | null; category?: string; brand_id?: string | null; clear_brand?: boolean }) =>
    browserApiFetch<DocumentTemplateInfo>(`/api/document-templates/${id}`, json(body, "PATCH")),
  deleteTemplate: (id: string) => browserApiFetch<null>(`/api/document-templates/${id}`, { method: "DELETE" }),
  duplicateTemplate: (id: string, name: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}/duplicate`, json({ name })),
  saveDraft: (id: string, body: { content: TemplateContent; lock_version: number | null; brand_mode?: "follow" | "pinned"; note?: string | null }, signal?: AbortSignal) =>
    browserApiFetch<{ revision: RevisionInfo; diagnostics: Diagnostic[] }>(`/api/document-templates/${id}/draft`, { ...json(body, "PUT"), signal: signal ?? AbortSignal.timeout(30_000) }),
  discardDraft: (id: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}/draft`, { method: "DELETE" }),
  validate: (content: TemplateContent, documentType: string) => browserApiFetch<{ diagnostics: Diagnostic[] }>("/api/document-templates/validate", json({ content, document_type: documentType })),
  publish: (id: string, note?: string | null) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}/publish`, json({ note: note ?? null })),
  archive: (id: string, archived: boolean) => browserApiFetch<DocumentTemplateInfo>(`/api/document-templates/${id}/archive`, json({ archived })),
  revisions: (id: string) => browserApiFetch<RevisionInfo[]>(`/api/document-templates/${id}/revisions`),
  revision: (id: string, revisionId: string) => browserApiFetch<{ revision: RevisionInfo; content: TemplateContent }>(`/api/document-templates/${id}/revisions/${revisionId}`),
  restoreRevision: (id: string, revisionId: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}/revisions/${revisionId}/restore`, { method: "POST" }),
  compare: (id: string, from: string, to: string) => browserApiFetch<RevisionDiff>(`/api/document-templates/${id}/compare?from=${from}&to=${to}`),
  thumbnailUrl: (id: string, version: string) => `/api/document-templates/${id}/thumbnail?v=${encodeURIComponent(version)}`,

  assignments: () => browserApiFetch<Assignment[]>("/api/document-template-assignments"),
  setAssignment: (body: { document_type: string; protocol_template_id?: string | null; template_id?: string | null; brand_id?: string | null }) =>
    browserApiFetch<Assignment | null>("/api/document-template-assignments", json(body, "PUT")),

  brands: (includeArchived = false) => browserApiFetch<Brand[]>(`/api/document-brands${includeArchived ? "?include_archived=true" : ""}`),
  createBrand: (body: { name: string; description?: string | null; preset?: string | null; from_brand_id?: string | null; tokens?: BrandTokens | null; is_default?: boolean }) =>
    browserApiFetch<Brand>("/api/document-brands", json(body)),
  updateBrand: (id: string, body: { lock_version: number; name?: string; description?: string | null; tokens?: BrandTokens; is_default?: boolean; note?: string | null }) =>
    browserApiFetch<Brand>(`/api/document-brands/${id}`, json(body, "PATCH")),
  archiveBrand: (id: string, archived: boolean) => browserApiFetch<Brand>(`/api/document-brands/${id}/archive`, json({ archived })),
  deleteBrand: (id: string) => browserApiFetch<null>(`/api/document-brands/${id}`, { method: "DELETE" }),
  brandRevisions: (id: string) => browserApiFetch<BrandRevision[]>(`/api/document-brands/${id}/revisions`),
  restoreBrandRevision: (id: string, revisionId: string) => browserApiFetch<Brand>(`/api/document-brands/${id}/revisions/${revisionId}/restore`, { method: "POST" }),

  assets: (kind?: "image" | "font") => browserApiFetch<DocumentAsset[]>(`/api/document-assets${kind ? `?kind=${kind}` : ""}`),
  uploadAsset: (file: File, kind: "image" | "font", category?: string | null, name?: string | null) => {
    const body = new FormData();
    body.append("kind", kind);
    if (category) body.append("category", category);
    if (name) body.append("name", name);
    body.append("file", file);
    return browserApiFetch<DocumentAsset>("/api/document-assets", { method: "POST", body, signal: AbortSignal.timeout(60_000) });
  },
  updateAsset: (id: string, body: { name?: string; category?: string }) => browserApiFetch<DocumentAsset>(`/api/document-assets/${id}`, json(body, "PATCH")),
  deleteAsset: (id: string) => browserApiFetch<null>(`/api/document-assets/${id}`, { method: "DELETE" }),
  assetReferences: (id: string) => browserApiFetch<AssetReference[]>(`/api/document-assets/${id}/references`),

  documentSettings: () => browserApiFetch<{ language: string | null }>("/api/document-settings"),
  updateDocumentSettings: (language: string | null) => browserApiFetch<{ language: string | null }>("/api/document-settings", json({ language }, "PATCH")),

  components: () => browserApiFetch<ReusableComponent[]>("/api/document-components"),
  createComponent: (body: { name: string; description?: string | null; category?: string | null; node: TemplateNode }) => browserApiFetch<ReusableComponent>("/api/document-components", json(body)),
  updateComponent: (id: string, body: { name?: string; description?: string | null; category?: string; node?: TemplateNode; lock_version?: number }) =>
    browserApiFetch<ReusableComponent>(`/api/document-components/${id}`, json(body, "PATCH")),
  deleteComponent: (id: string) => browserApiFetch<null>(`/api/document-components/${id}`, { method: "DELETE" }),
};

export function previewDocument(request: DocumentRequest, maxPages = 4, signal?: AbortSignal) {
  return browserApiFetch<PreviewResult>(`/api/documents/preview?max_pages=${maxPages}`, {
    method: "POST",
    body: JSON.stringify(request),
    signal: signal ?? AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
}

export function renderDocument(request: DocumentRequest) {
  return browserApiFetch<DocumentExport>("/api/documents/render", {
    method: "POST",
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
}

export function listExports(params: { protocolId?: string | null; documentType?: string | null; limit?: number; offset?: number } = {}) {
  const query = new URLSearchParams();
  if (params.protocolId) query.set("protocol_id", params.protocolId);
  if (params.documentType) query.set("document_type", params.documentType);
  query.set("limit", String(params.limit ?? 25));
  query.set("offset", String(params.offset ?? 0));
  return browserApiFetch<DocumentExport[]>(`/api/documents/exports?${query}`);
}

/** CSV/XLSX/ICS/Markdown als Datei laden (Download im Browser). */
export async function exportDocumentFile(request: DocumentRequest, format: "csv" | "xlsx" | "ics" | "markdown"): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch("/api/documents/export", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...request, format }),
    signal: AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
  if (!response.ok) {
    let message = "";
    try {
      const detail = (await response.json())?.detail;
      message = typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : "";
    } catch {
      message = "";
    }
    throw new ApiError(message, "backend", response.status);
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? `export.${format === "markdown" ? "md" : format}` };
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function fetchSourceOptions(source: string, protocolId?: string | null) {
  const query = protocolId ? `?protocol_id=${encodeURIComponent(protocolId)}` : "";
  return browserApiFetch<SourceOption[]>(`/api/documents/sources/${source}${query}`);
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Löst ein $ref im Pydantic-Schema auf. */
export function resolveSchema(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop() ?? "";
    return root.$defs?.[name] ?? {};
  }
  return schema;
}

/** Optionale Felder (anyOf mit null) auf den eigentlichen Typ reduzieren. */
export function unwrapNullable(schema: JsonSchema, root: JsonSchema): JsonSchema {
  const resolved = resolveSchema(schema, root);
  if (resolved.anyOf) {
    const inner = resolved.anyOf.find((option) => option.type !== "null");
    if (inner) return { ...resolveSchema(inner, root), "x-source": resolved["x-source"] ?? inner["x-source"], "x-widget": resolved["x-widget"] ?? inner["x-widget"] };
  }
  return resolved;
}

/** Standardwerte eines Parameter-Schemas (für neue Komponenten). */
export function defaultParams(schema: JsonSchema): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(schema.properties ?? {})) {
    if (property.default !== undefined && property.default !== null) params[name] = property.default;
  }
  return params;
}
