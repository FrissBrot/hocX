// Typen und Aufrufe des Document Studio (Vorlagen, Brand-Profile, Assets, Komponenten,
// Zuweisungen, Katalog) und des Export Center (Export, Vorschau, Zusatzformate, Historie).
// Schnittstelle siehe backend/app/api/routes/document_studio.py und documents.py.

import { ApiError, browserApiFetch } from "@/lib/api/client";
import type { BrandTokens, Condition, TemplateContent, TemplateNode } from "@/lib/documents/layout";

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
  /** Elementarten, deren Darstellung ein Block dieser Komponente übersteuern kann */
  appearance_kinds: string[];
};

// Grundstil bzw. Design: ``layout`` übernimmt das Brand Studio in den Seitenaufbau, ``legacy`` =
// früherer Grundstil, nur noch für Profile, die ihn schon nutzen
export type AppearanceBaseInfo = {
  layout: { heading_style: string; table_style: string; radius: number; heading_number_style?: string; responsible_display?: string };
  elements: Record<string, string>;
  legacy?: boolean;
};
export type AppearanceCatalog = { variants: Record<string, string[]>; brand_only: string[]; corner_kinds: string[]; bases: Record<string, AppearanceBaseInfo> };

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
  appearance: AppearanceCatalog;
  bindings: BindingInfo[];
  document_types: DocumentTypeInfo[];
  categories: string[];
  modes: EditorMode[];
  color_references: string[];
  fonts: string[];
  brand_presets: string[];
  simple: SimpleCatalog;
};

// Modus «Einfach» (backend/app/documents/simple.py): bekannte Bausteine mit 1–3 Einstellungen
export type SimpleSetting =
  | { key: string; kind: "toggle"; path: string; default: boolean }
  | { key: string; kind: "variant"; appearance: string; options: string[] }
  | { key: string; kind: "text"; path: string }
  | { key: string; kind: "markdown"; path: string }
  | { key: string; kind: "names"; path: string }
  | { key: string; kind: "image"; path: string }
  | { key: string; kind: "multi"; path: string; options: string[]; default: string[] }
  | { key: string; kind: "condition" };
export type SimpleBlock = {
  key: string;
  match: { type: string | string[]; component?: string[]; role?: string[] };
  settings: SimpleSetting[];
};
export type SimpleCatalog = {
  blocks: SimpleBlock[];
  add: string[];
  styles: string[];
  conditions: Record<string, Condition>;
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
  // Gestaltung, die allein zu einer Sitzungsvorlage gehört
  session_template_id?: string | null;
  session_template_name?: string | null;
  // Sitzungsvorlagen, die diese Gestaltung verwenden (eigene Zuweisung oder Standard)
  used_in?: SessionTemplateRef[];
  // Bei Kopien: Name der Gestaltung, von der sie abstammt
  source_template_name?: string | null;
  // Übernommenes Katalog-Design (Alpin, Kreide …)
  catalog_key?: string | null;
  // Neuere Katalog-Fassung der Systemvorlage, von der diese Kopie stammt
  update_revision_no?: number | null;
  // Exporte der letzten zwölf Monate, letzter Export
  export_count?: number;
  last_export_at?: string | null;
  // Nicht verwendet, lässt sich beim Aufräumen archivieren
  cleanup_candidate?: boolean;
};

export type SessionTemplateRef = { id: string; name: string };

/** Geltende Seitengestaltung eines Sitzungsdokuments einer Sitzungsvorlage. */
export type SessionDesign = {
  document_type: "protocol" | "invitation" | "agenda";
  template_id: string;
  template_name: string;
  template_origin: "system" | "tenant" | "copy";
  template_system_key: string | null;
  source: "protocol_template" | "tenant_default" | "platform_default" | "fallback";
  owned: boolean;
  // Alle Sitzungsvorlagen, die diese Gestaltung verwenden (inkl. der aktuellen)
  used_in: SessionTemplateRef[];
  // Gestaltung des Mandanten, die der Benutzer bearbeiten darf (keine hocX-Vorlage)
  editable: boolean;
};

/** Gestaltungsbeispiel (backend/app/documents/examples.py), Namen über documentStudio.examples.items. */
// Traktanden und Bausteine der Sitzungsvorlage, der eine Gestaltung gehört (Darstellung je
// Baustein im Designer, Knoten «Protokollinhalt»: block_appearance[key])
export type ProtocolStructureBlock = { key: string; title: string; element_type: string; element_type_id: number; appearance_kinds: string[] };
export type ProtocolStructure = {
  owned: boolean;
  session_template_name: string | null;
  elements: { id: string; title: string; blocks: ProtocolStructureBlock[] }[];
};

export type DesignExample = {
  key: string;
  document_type: string;
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
  // Aktive Vorlagen, die dieses Erscheinungsbild nutzen; Verweis aus einer Zuweisung
  template_count?: number;
  assigned?: boolean;
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
  // Aktive Brand-Profile, Vorlagen und Komponenten, die es nutzen
  used_in?: string[];
  // Anzahl gleicher Dateien im Verein (0 = keine Duplikate) und Schlüssel ihrer Gruppe
  duplicate_count?: number;
  duplicate_group?: string | null;
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
  // Vorlagen-Editor: Traktanden aus dieser Sitzungsvorlage (Inhalte aus protocol_id bzw. der letzten Sitzung)
  protocol_template_id?: string | null;
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
  // Nur mit nodeBoxes: wo jeder Knoten steht (Seite ab 1, pt), Bausteine als «source:<schlüssel>»
  node_boxes?: NodeBox[] | null;
  page_size?: [number, number] | null;
};

export type NodeBox = { node_id: string; page: number; x: number; y: number; width: number; height: number };

export type SourceOption = { id: string; label: string; detail?: string | null };

// ── Aufrufe ─────────────────────────────────────────────────────────────────

const json = (body: unknown, method = "POST"): RequestInit => ({ method, body: JSON.stringify(body) });

export const studioApi = {
  capabilities: () => browserApiFetch<Capabilities>("/api/document-studio/capabilities"),
  sessionDesigns: (templateId: string) => browserApiFetch<SessionDesign[]>(`/api/document-studio/session-templates/${templateId}/designs`),
  customizeSessionDesign: (templateId: string, documentType: string, name: string) =>
    browserApiFetch<DocumentTemplateDetail>(`/api/document-studio/session-templates/${templateId}/designs/${documentType}`, json({ name })),
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
  archiveUnused: (templateIds: string[]) => browserApiFetch<{ archived: number }>("/api/document-templates/archive-unused", json({ template_ids: templateIds })),
  revisions: (id: string) => browserApiFetch<RevisionInfo[]>(`/api/document-templates/${id}/revisions`),
  revision: (id: string, revisionId: string) => browserApiFetch<{ revision: RevisionInfo; content: TemplateContent }>(`/api/document-templates/${id}/revisions/${revisionId}`),
  restoreRevision: (id: string, revisionId: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-templates/${id}/revisions/${revisionId}/restore`, { method: "POST" }),
  compare: (id: string, from: string, to: string) => browserApiFetch<RevisionDiff>(`/api/document-templates/${id}/compare?from=${from}&to=${to}`),
  thumbnailUrl: (id: string, version: string) => `/api/document-templates/${id}/thumbnail?v=${encodeURIComponent(version)}`,

  protocolStructure: (templateId: string) => browserApiFetch<ProtocolStructure>(`/api/document-templates/${encodeURIComponent(templateId)}/protocol-structure`),
  listExamples: () => browserApiFetch<DesignExample[]>("/api/document-studio/examples"),
  importExample: (key: string, name: string) => browserApiFetch<DocumentTemplateDetail>(`/api/document-studio/examples/${encodeURIComponent(key)}/import`, json({ name })),
  exampleThumbnailUrl: (key: string) => `/api/document-studio/examples/${encodeURIComponent(key)}/thumbnail`,
  // Katalog-Design mit dem Erscheinungsbild des Vereins; ``version`` macht Änderungen am Profil sichtbar
  exampleBrandThumbnailUrl: (key: string, version: string) => `/api/document-studio/examples/${encodeURIComponent(key)}/brand-thumbnail?v=${encodeURIComponent(version)}`,

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
  mergeDuplicateAssets: () => browserApiFetch<{ removed: number }>("/api/document-assets/merge-duplicates", { method: "POST" }),

  documentSettings: () => browserApiFetch<{ language: string | null }>("/api/document-settings"),
  updateDocumentSettings: (language: string | null) => browserApiFetch<{ language: string | null }>("/api/document-settings", json({ language }, "PATCH")),

  components: () => browserApiFetch<ReusableComponent[]>("/api/document-components"),
  createComponent: (body: { name: string; description?: string | null; category?: string | null; node: TemplateNode }) => browserApiFetch<ReusableComponent>("/api/document-components", json(body)),
  updateComponent: (id: string, body: { name?: string; description?: string | null; category?: string; node?: TemplateNode; lock_version?: number }) =>
    browserApiFetch<ReusableComponent>(`/api/document-components/${id}`, json(body, "PATCH")),
  deleteComponent: (id: string) => browserApiFetch<null>(`/api/document-components/${id}`, { method: "DELETE" }),
};

export function previewDocument(request: DocumentRequest, maxPages = 4, signal?: AbortSignal, options?: { nodeBoxes?: boolean }) {
  return browserApiFetch<PreviewResult>(`/api/documents/preview?max_pages=${maxPages}${options?.nodeBoxes ? "&node_boxes=true" : ""}`, {
    method: "POST",
    body: JSON.stringify(request),
    signal: signal ?? AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
}

// ── Arbeitsfläche des Designers ─────────────────────────────────────────────

/** Brand-Werte, wie sie der Typst-Compile verwendet (brand_service.resolve_brand → typst). */
export type ResolvedBrand = {
  colors: Record<string, string>;
  custom_colors: Record<string, string>;
  fonts: { body: string[]; heading: string[] };
  typography: {
    base_size: number;
    size_title: number;
    size_subtitle: number;
    size_h1: number;
    size_h2: number;
    size_h3: number;
    size_small: number;
    weight_body: number;
    weight_heading: number;
    line_height: number;
    letter_spacing_heading: number;
    heading_transform: "none" | "upper";
  };
  layout: { paragraph_gap: number; section_gap: number; heading_style: string; table_style: string; border_width: number; radius: number; heading_number_style?: string; responsible_display?: string; empty_blocks?: string };
  appearance: Record<string, { variant: string | null; radius: number }>;
};

/** Aufgelöste Werte je Knoteninstanz; Schlüssel `<node_id>@<instanz>` (compiler.CanvasHints). */
export type CanvasHints = {
  hidden: Record<string, "condition" | "empty">;
  texts: Record<string, { inlines?: (string | null)[]; text?: string }>;
  rows: Record<string, string[] | string[][]>;
  repeats: Record<string, number>;
  // Alle Überschriften in Dokumentreihenfolge (Nummerierung, Inhaltsverzeichnis)
  headings: { level: number; text: string; outlined: boolean }[];
  heading_index: Record<string, number>;
};

export type CanvasData = {
  hints: CanvasHints;
  brand: ResolvedBrand;
  numbering: boolean;
  snippets: Record<string, string>;
  snippet_pad: number;
  diagnostics: Diagnostic[];
};

export function previewCanvas(request: DocumentRequest, signal?: AbortSignal) {
  return browserApiFetch<CanvasData>("/api/documents/preview/canvas", {
    method: "POST",
    body: JSON.stringify(request),
    signal: signal ?? AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
}

/** PDF-Auftrag (POST /api/documents/render, 202): der job-worker rendert, der Client fragt den Stand ab. */
export type DocumentRenderJob = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  export: DocumentExport | null;
  error_status: number | null;
  error: unknown;
  created_at: string;
};

// Wie lange höchstens auf einen PDF-Auftrag gewartet wird (Warteschlange plus Compile, mit Reserve).
export const RENDER_JOB_TIMEOUT_MS = 10 * 60_000;

function renderJobError(job: DocumentRenderJob): ApiError {
  const detail = job.error;
  const message = typeof detail === "string" ? detail
    : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string" ? (detail as { message: string }).message
    : "";
  const status = job.error_status ?? 500;
  return new ApiError(message, status >= 500 ? "backend" : "validation", status, detail);
}

/** Wartet, bis ein PDF-Auftrag fertig ist (Abfrage mit wachsendem Abstand, 0.75 s bis 3 s). */
export async function waitForRenderJob(job: DocumentRenderJob, timeoutMs = RENDER_JOB_TIMEOUT_MS): Promise<DocumentExport> {
  let current = job;
  let delay = 750;
  const deadline = Date.now() + timeoutMs;
  while (current.status === "queued" || current.status === "running") {
    if (Date.now() > deadline) throw new ApiError("", "timeout");
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(3000, Math.round(delay * 1.5));
    current = await browserApiFetch<DocumentRenderJob>(`/api/documents/render-jobs/${current.id}`);
  }
  if (current.status === "failed" || !current.export) throw renderJobError(current);
  return current.export;
}

/** PDF erzeugen: Auftrag anlegen und auf das Ergebnis warten (Concurrency-Audit Paket 10). Rechte
 * und Vorlage prüft der Server sofort; das Rendern übernimmt der job-worker. */
export async function renderDocument(request: DocumentRequest): Promise<DocumentExport> {
  const job = await browserApiFetch<DocumentRenderJob>("/api/documents/render", {
    method: "POST",
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(DOCUMENT_TIMEOUT_MS),
  });
  return waitForRenderJob(job);
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
