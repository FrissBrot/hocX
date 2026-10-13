// Typen und Aufrufe der Dokument-Engine (/api/documents/*, Hausstile, Rezepte).
// Schnittstelle siehe backend/app/api/routes/documents.py.

import { ApiError, browserApiFetch } from "@/lib/api/client";

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

export type CatalogBlock = {
  type: string;
  group: string;
  access: "reader" | "writer" | "finance";
  params_schema: JsonSchema;
};

export type BlockSpec = {
  type: string;
  title?: string | null;
  hide_if_empty?: boolean;
  level?: number;
  params: Record<string, unknown>;
};

export type DocumentTypeInfo = { key: string; needs_protocol: boolean; blocks: BlockSpec[] };

export type DocumentCatalog = {
  blocks: CatalogBlock[];
  document_types: DocumentTypeInfo[];
  style_keys: string[];
  languages: string[];
};

export type ExportOptions = {
  title?: string | null;
  subtitle?: string | null;
  title_page?: string | null;
  toc?: string | null;
  toc_block_titles?: boolean | null;
  numbering?: boolean | null;
  orientation?: string | null;
  watermark?: boolean | null;
};

export type DocumentRequest = {
  document_type?: string | null;
  recipe_id?: string | null;
  protocol_id?: string | null;
  blocks?: BlockSpec[] | null;
  params?: Record<string, unknown>;
  style_id?: string | null;
  /** Ungespeicherte Tokens für die Live-Vorschau der Hausstil-Einstellungen. */
  style_override?: { style_key: string; tokens: StyleTokens } | null;
  options?: ExportOptions;
  language?: string | null;
};

export type DocumentExport = {
  id: string;
  document_type: string;
  title: string | null;
  version_label: string | null;
  signature_level: string | null;
  language: string | null;
  style_key: string | null;
  generated_file_id: string | null;
  content_url: string | null;
  created_at: string;
};

export type StyleTokens = {
  primary_color: string;
  secondary_color: string;
  font: string;
  custom_fonts: { regular: string | null; bold: string | null; italic: string | null; bold_italic: string | null };
  base_size: 10 | 11 | 12;
  line_spacing: string;
  margins: string;
  orientation: string;
  logo_asset_id: string | null;
  footer_image_asset_id: string | null;
  sender: string;
  place: string;
  header: string;
  footer: string;
  title_page: string;
  toc: string;
  numbering: boolean;
  toc_block_titles: boolean;
  watermark_draft: boolean;
};

export type DocumentStyle = {
  id: string;
  name: string;
  style_key: string;
  tokens: StyleTokens;
  is_default: boolean;
  version: number;
  updated_at: string;
};

export type DocumentStyleAsset = {
  id: string;
  kind: "image" | "font";
  name: string;
  original_name: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  font_family: string | null;
  content_url: string;
  created_at: string;
};

export type DocumentRecipe = {
  id: string;
  name: string;
  document_type: string;
  blocks: BlockSpec[];
  options: ExportOptions;
  style_id: string | null;
  language: string | null;
  updated_at: string;
};

export type SourceOption = { id: string; label: string; detail?: string | null };

export const DOCUMENT_TIMEOUT_MS = 120_000;

export function fetchCatalog() {
  return browserApiFetch<DocumentCatalog>("/api/documents/catalog");
}

export function previewDocument(request: DocumentRequest, maxPages = 3, signal?: AbortSignal) {
  return browserApiFetch<{ pages: string[] }>(`/api/documents/preview?max_pages=${maxPages}`, {
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
      message = (await response.json())?.detail ?? "";
    } catch {
      message = "";
    }
    throw new ApiError(typeof message === "string" ? message : "", "backend", response.status);
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

export function listStyles() {
  return browserApiFetch<DocumentStyle[]>("/api/document-styles");
}

export function listRecipes() {
  return browserApiFetch<DocumentRecipe[]>("/api/document-recipes");
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

/** Standardwerte eines Parameter-Schemas (für neue Blöcke). */
export function defaultParams(schema: JsonSchema): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(schema.properties ?? {})) {
    if (property.default !== undefined && property.default !== null) params[name] = property.default;
  }
  return params;
}
