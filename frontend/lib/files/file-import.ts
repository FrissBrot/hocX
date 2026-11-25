// Datei-Import (Backend: routes/cloud_import.py): Typen und reine Hilfsfunktionen für den Wizard.

/** API-Anbieter (Backend: services/cloud_import/providers); angeboten werden nur konfigurierte. */
export type CloudProviderKey = "microsoft" | "google_drive" | "google_photos" | "dropbox" | "webdav";
export type ImportSource = "zip" | "folder" | CloudProviderKey;
export type ImportTypeFilter = "all" | "images" | "documents";
export type ImportJobStatus =
  | "draft"
  | "listing"
  | "ready"
  | "queued"
  | "running"
  | "needs_reauth"
  | "cancel_requested"
  | "cancelled"
  | "done"
  | "failed";
export type ImportItemStatus = "listed" | "queued" | "staged" | "imported" | "duplicate" | "skipped" | "failed" | "cancelled";

export type ImportRuleAction =
  | "add_tags"
  | "set_date"
  | "skip"
  | "add_to_album"
  | "folder_to_album";

export type ImportRule = {
  id: string;
  enabled: boolean;
  match: {
    folder?: string | null;
    path_glob?: string | null;
    name_regex?: string | null;
    kind: "all" | "images" | "documents";
    case_sensitive: boolean;
  };
  action: {
    type: ImportRuleAction;
    tags?: string[];
    date?: string | null;
    album_id?: string | null;
    album_name?: string | null;
    folder_level?: "parent" | "top";
  };
};

export type ImportJob = {
  id: string;
  source: ImportSource;
  status: ImportJobStatus;
  type_filter: ImportTypeFilter;
  include_gps: boolean;
  folder_tags: boolean;
  albums_enabled: boolean;
  takeout: boolean;
  rules: ImportRule[];
  total_items: number;
  total_bytes: number;
  archives: number;
  error: string | null;
  is_owner: boolean;
  requested_by_name: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_progress_at: string | null;
  counts: Partial<Record<ImportItemStatus, number>>;
  codes: Record<string, number>;
  processed_bytes: number;
  albums: { name: string; reused: boolean; candidates: number }[];
  // API-Quellen
  connection?: CloudConnection | null;
  selection_count?: number;
  listing?: { folders: number; queued_folders: number; errors: number } | null;
  not_before?: string | null;
};

export type CloudConnection = {
  provider: CloudProviderKey;
  status: "active" | "needs_reauth";
  account_label: string | null;
  account_kind: string | null;
  tier: string | null;
  tiers: string[];
};

export type CloudProvider = {
  key: CloudProviderKey;
  tiers: string[];
  default_tier: string;
  info: Record<string, string>;
};

export type CloudNode = {
  ref: string;
  name: string;
  kind: "folder" | "file";
  size: number | null;
  modified_at: string | null;
  child_count: number | null;
  available: boolean;
  requires_tier: string | null;
  selectable: boolean;
  label_key: string | null;
  file_kind: "image" | "document" | "other" | null;
};

export type ImportRuleError = { rule_id: string; field: string; code: string };

export type ImportPreviewItem = {
  path: string;
  kind: "image" | "document" | "other";
  size: number;
  import: boolean;
  reason: string | null;
  tags: string[];
  date: string | null;
  date_source?: "rule" | "takeout" | null;
  albums: string[];
  rules: string[];
  conflict: boolean;
};

export type ImportPreview = {
  summary: {
    total: number;
    importable: number;
    images: number;
    documents: number;
    planned_bytes: number;
    conflicts: number;
    skipped: Record<string, number>;
    per_rule: Record<string, number>;
  };
  quota: { limit_bytes: number | null; used_bytes: number; planned_bytes: number; fits: boolean };
  errors: ImportRuleError[];
  items: ImportPreviewItem[];
  filtered_total: number;
  folders: string[];
  saved: boolean;
  existing_albums: string[];
};

export type ImportReportItem = {
  path: string;
  kind: "image" | "document" | "other";
  size: number;
  status: ImportItemStatus;
  result_code: string | null;
  tags: string[];
  estimated_date: string | null;
  date_source?: "rule" | "takeout" | null;
  albums: string[];
  conflict: boolean;
  file_id: string | null;
};

export const ACTIVE_STATUSES: ImportJobStatus[] = ["draft", "listing", "ready", "queued", "running", "needs_reauth", "cancel_requested"];

export function isCloudSource(source: ImportSource): source is CloudProviderKey {
  return source !== "zip" && source !== "folder";
}

/** Parameter, mit denen der OAuth-Callback in den Wizard zurückspringt (Abschluss-Token im Fragment). */
export function readCloudReturn(search: string, hash: string): { job: string | null; error: string | null; notice: string | null; finish: string | null } {
  const query = new URLSearchParams(search);
  const fragment = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  return {
    job: query.get("job"),
    error: query.get("cloud_error"),
    notice: query.get("cloud_notice"),
    finish: fragment.get("cloud_finish"),
  };
}
export const RUNNING_STATUSES: ImportJobStatus[] = ["queued", "running", "cancel_requested"];

export function isActive(job: ImportJob): boolean {
  return ACTIVE_STATUSES.includes(job.status);
}

/** Eine Datei mit ihrem Pfad relativ zum gewählten Ordner. */
export type PathedFile = { path: string; file: File };

const HIDDEN = /(^|\/)(\.[^/]*|__MACOSX|Thumbs\.db|desktop\.ini)(\/|$)/i;

/** Systemdateien (.DS_Store, __MACOSX, Thumbs.db) gar nicht erst melden. */
export function isHiddenPath(path: string): boolean {
  return HIDDEN.test(path);
}

/** Dateien aus einem Ordner-Input (webkitdirectory) mit relativem Pfad. */
export function pathedFromInput(files: FileList | File[]): PathedFile[] {
  return Array.from(files)
    .map((file) => ({ path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name, file }))
    .filter((entry) => !isHiddenPath(entry.path));
}

type Entry = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  fullPath?: string;
  file?: (success: (file: File) => void, failure: (error: unknown) => void) => void;
  createReader?: () => { readEntries: (success: (entries: Entry[]) => void, failure: (error: unknown) => void) => void };
};

async function readEntry(entry: Entry, prefix: string, out: PathedFile[], limit: number): Promise<void> {
  if (out.length >= limit) return;
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (isHiddenPath(path)) return;
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) => entry.file!(resolve, reject));
    out.push({ path, file });
    return;
  }
  if (!entry.isDirectory || !entry.createReader) return;
  const reader = entry.createReader();
  // readEntries liefert in Blöcken (Chrome: 100) - bis zur leeren Antwort weiterlesen.
  for (;;) {
    const batch = await new Promise<Entry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    for (const child of batch) await readEntry(child, path, out, limit);
    if (out.length >= limit) break;
  }
}

/** Ordner per Drag & Drop: alle Dateien rekursiv mit Pfad (der gezogene Ordner ist die Wurzel). */
export async function pathedFromDataTransfer(dataTransfer: DataTransfer, limit: number): Promise<PathedFile[]> {
  const entries: Entry[] = [];
  for (const item of Array.from(dataTransfer.items ?? [])) {
    const entry = (item.webkitGetAsEntry?.() ?? null) as unknown as Entry | null;
    if (entry) entries.push(entry);
  }
  if (!entries.length) return pathedFromInput(Array.from(dataTransfer.files));
  const out: PathedFile[] = [];
  for (const entry of entries) await readEntry(entry, "", out, limit);
  return out;
}

/** Pfade wie das Backend vergleichen: «\» → «/», ohne leere/«.»-Segmente, NFC. */
export function normalizeImportPath(path: string): string {
  return path
    .normalize("NFC")
    .replace(/\\/g, "/")
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== "." && segment !== "..")
    .join("/");
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let index = 0; index < items.length; index += size) out.push(items.slice(index, index + size));
  return out;
}

/** Upload-Pakete: höchstens maxFiles Dateien und maxBytes (eine grössere Datei allein). */
export function uploadBatches(files: PathedFile[], maxFiles: number, maxBytes: number): PathedFile[][] {
  const batches: PathedFile[][] = [];
  let current: PathedFile[] = [];
  let bytes = 0;
  for (const entry of files) {
    if (current.length && (current.length >= maxFiles || bytes + entry.file.size > maxBytes)) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(entry);
    bytes += entry.file.size;
  }
  if (current.length) batches.push(current);
  return batches;
}

export const ALBUM_ACTIONS: ImportRuleAction[] = ["add_to_album", "folder_to_album"];

let ruleCounter = 0;

export function newRule(type: ImportRuleAction = "add_tags"): ImportRule {
  ruleCounter += 1;
  return {
    id: `r${Date.now().toString(36)}${ruleCounter}`,
    enabled: true,
    match: { folder: null, path_glob: null, name_regex: null, kind: "all", case_sensitive: false },
    action: { type, tags: [], date: null, album_id: null, album_name: null, folder_level: "parent" },
  };
}

/** Nur die Felder, die zur gewählten Aktion gehören, ans Backend (extra=forbid erlaubt die übrigen
 * zwar, so bleibt die gespeicherte Regel aber übersichtlich). */
export function cleanRule(rule: ImportRule): ImportRule {
  const { type } = rule.action;
  const action: ImportRule["action"] = { type };
  if (type === "add_tags") action.tags = rule.action.tags ?? [];
  if (type === "set_date") action.date = rule.action.date || null;
  if (type === "add_to_album") {
    action.album_id = rule.action.album_id || null;
    action.album_name = rule.action.album_id ? null : rule.action.album_name || null;
  }
  if (type === "folder_to_album") action.folder_level = rule.action.folder_level ?? "parent";
  const match: ImportRule["match"] = {
    kind: rule.match.kind,
    case_sensitive: rule.match.case_sensitive,
    folder: rule.match.folder || null,
    path_glob: rule.match.path_glob?.trim() || null,
    name_regex: rule.match.name_regex || null,
  };
  return { id: rule.id, enabled: rule.enabled, match, action };
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length || from === to) return items;
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** Anteil 0..100 der erledigten Dateien eines laufenden Imports. */
export function importProgress(job: ImportJob): number {
  const counts = job.counts;
  const open = (counts.queued ?? 0) + (counts.staged ?? 0) + (counts.listed ?? 0);
  const done = (counts.imported ?? 0) + (counts.duplicate ?? 0) + (counts.failed ?? 0) + (counts.cancelled ?? 0);
  const total = open + done;
  return total ? Math.round((done / total) * 100) : 0;
}

/** Fehlercode aus einer ApiError (detail = {code, params}). */
export function apiErrorCode(error: unknown): string | null {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && "code" in detail && typeof (detail as { code: unknown }).code === "string") {
    return (detail as { code: string }).code;
  }
  return null;
}

/** Startet die Anmeldung beim Anbieter (Navigation im selben Fenster; Rückkehr über den Callback). */
export async function startCloudLogin(
  fetcher: <T>(path: string, init?: RequestInit) => Promise<T>,
  jobId: string,
  provider: CloudProviderKey,
  options: { tier?: string | null; selectAccount?: boolean } = {},
): Promise<void> {
  const result = await fetcher<{ authorize_url: string }>(`/api/cloud-import/oauth/${provider}/start`, {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, tier: options.tier ?? null, select_account: options.selectAccount ?? false }),
  });
  window.location.assign(result.authorize_url);
}

// --- Google (Drive-Picker, Fotos-Sitzung) -----------------------------------------------------

/** Eigene Seite des Google Pickers (gelockerte CSP nur dort, lib/csp.ts). */
export const GOOGLE_PICKER_PAGE = "/files/import/google-picker";
/** Loader des Google Pickers bzw. sein Nachbau im E2E-Stack (Backend, nur CLOUD_IMPORT_FAKE_PROVIDERS). */
export const GOOGLE_PICKER_SCRIPT = "https://apis.google.com/js/api.js";
export const GOOGLE_PICKER_FAKE_SCRIPT = "/api/cloud-import/fake-google/picker.js";
const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type GooglePickerConfig = {
  access_token: string;
  api_key: string;
  app_id: string;
  expires_in: number;
  max_items: number;
  fake: boolean;
};

export type PhotosSession = { picker_uri: string; poll_seconds: number; timeout_seconds: number | null };
export type PhotosPoll = { done: boolean; poll_seconds: number; job: ImportJob };

/** Auswahl-Art eines Anbieters ohne Ordnerbaum (Backend: provider.public_info()["selection"]). */
export function cloudSelectionMode(provider: CloudProvider | null): "tree" | "google_picker" | "photos_picker" {
  const mode = provider?.info.selection;
  return mode === "google_picker" || mode === "photos_picker" ? mode : "tree";
}

/** Gültige Auftrags-ID aus der Adresszeile der Picker-Seite, sonst null. */
export function pickerJobId(search: string): string | null {
  const job = new URLSearchParams(search).get("job");
  return job && JOB_ID.test(job) ? job : null;
}

/** Zurück in den Wizard - immer als voller Seitenwechsel (die Picker-Seite hat eine eigene CSP). */
export function wizardUrl(jobId: string | null): string {
  return jobId ? `/files/import?job=${encodeURIComponent(jobId)}` : "/files/import";
}

/** Nur IDs gewählter Dateien (Ordner gibt drive.file nicht frei), ohne Doppelte, höchstens max. */
export function pickedFileIds(docs: { id?: unknown; mimeType?: unknown }[], max: number): string[] {
  const ids = docs
    .filter((doc) => typeof doc.id === "string" && /^[A-Za-z0-9_-]{1,300}$/.test(doc.id) && doc.mimeType !== "application/vnd.google-apps.folder")
    .map((doc) => doc.id as string);
  return Array.from(new Set(ids)).slice(0, max);
}

/** Nur Auswahlseiten von Google Fotos öffnen (Backend prüft das auch); im E2E-Stack der Nachbau
 *  auf der eigenen Origin. */
export function isPhotosPickerUri(uri: string, origin: string): boolean {
  try {
    const url = new URL(uri);
    if (url.protocol === "https:" && url.host === "photos.google.com") return true;
    return url.origin === origin && url.pathname.startsWith("/api/cloud-import/fake-google/photos/");
  } catch {
    return false;
  }
}

/** Google Fotos schliesst das Auswahlfenster selbst, wenn die URI auf «/autoclose» endet. */
export function photosPickerUrl(uri: string): string {
  return uri.endsWith("/autoclose") ? uri : `${uri.replace(/\/$/, "")}/autoclose`;
}

export type WebdavPreset = "kdrive" | "nextcloud" | "generic";

/** Body für POST /api/cloud-import/jobs/{id}/webdav/connect: nur die Felder der gewählten Vorlage. */
export function webdavConnectBody(input: {
  preset: WebdavPreset;
  server: string;
  kdriveId: string;
  url: string;
  username: string;
  password: string;
}): Record<string, string> {
  const body: Record<string, string> = { preset: input.preset, username: input.username.trim(), password: input.password };
  if (input.preset === "kdrive" && input.kdriveId.trim()) body.kdrive_id = input.kdriveId.trim();
  if (input.preset === "nextcloud") body.server = input.server.trim();
  if (input.preset === "generic") body.url = input.url.trim();
  return body;
}

/** Anbieter mit Zugangsdaten statt OAuth (WebDAV). */
export function usesCredentials(provider: { info: Record<string, string> } | null | undefined): boolean {
  return provider?.info.auth === "credentials";
}
