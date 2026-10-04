export const SUPPORTED_UPLOAD_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "gif", "webp", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pages", "key", "numbers", "heic", "heif"];

// Extracted from upload-form.tsx (audit A5, 2026-08-16) so the client-side file validation
// - the reviewer's only defense before a request goes out from this unauthenticated public
// form - is a plain, unit-testable function instead of logic only reachable by rendering the
// whole component. Server-side validation is still authoritative (see abgabebox-backend); this
// is purely the first line of feedback for the person uploading.
//
// Returns a machine-readable `code` (+ `params` for the message's placeholders) instead of a
// finished text: this is a plain function, not a component, so it cannot call useTranslations()
// itself - the caller (upload-form.tsx) maps `code` to messages.upload.errors.<code> via
// next-intl. Keeps this file free of any UI-language concern and easy to unit-test against the
// stable code instead of brittle, locale-dependent substring text.
export type UploadValidationError =
  | { code: "tooManyFiles" }
  | { code: "selectionTooLarge" }
  | { code: "maxFilesTotal"; params: { maxFiles: number; remaining: number } }
  | { code: "unsupportedType"; params: { filename: string } }
  | { code: "disallowedType"; params: { filename: string; allowed: string } }
  | { code: "fileTooLarge"; params: { filename: string; maxFileSizeMb: number } };

export type UploadValidationResult = { ok: true } | ({ ok: false } & UploadValidationError);

export function getExtension(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts.pop()!.toLowerCase() : "";
}

export function validateUploadFiles(
  selected: File[],
  {
    maxFiles,
    allowedFileTypes,
    maxFileSizeMb,
    alreadyUploaded = 0,
  }: { maxFiles: number | null; allowedFileTypes: string[]; maxFileSizeMb: number; alreadyUploaded?: number }
): UploadValidationResult {
  if (selected.length > 50) return { ok: false, code: "tooManyFiles" };
  if (selected.reduce((sum, file) => sum + file.size, 0) > 150 * 1024 ** 2) {
    return { ok: false, code: "selectionTooLarge" };
  }
  // maxFiles = null bedeutet unbegrenzt viele Dateien (siehe Admin-Bereich, Feld "Max.
  // Dateien" leer gelassen). Das Limit gilt kumulativ ueber alle bisherigen Uploads dieses
  // Elements hinweg, nicht nur fuer diese eine Auswahl - siehe alreadyUploaded.
  if (maxFiles !== null) {
    const remaining = Math.max(0, maxFiles - alreadyUploaded);
    if (selected.length > remaining) {
      return { ok: false, code: "maxFilesTotal", params: { maxFiles, remaining } };
    }
  }
  const unsupported = selected.find((file) => !SUPPORTED_UPLOAD_EXTENSIONS.includes(getExtension(file.name)));
  if (unsupported) {
    return { ok: false, code: "unsupportedType", params: { filename: unsupported.name } };
  }
  if (allowedFileTypes.length > 0) {
    const allowed = allowedFileTypes.map((t) => t.toLowerCase());
    const typeLabel = allowedFileTypes.map((t) => t.toUpperCase()).join(", ");
    const wrongType = selected.find((f) => !allowed.includes(getExtension(f.name)));
    if (wrongType) {
      return { ok: false, code: "disallowedType", params: { filename: wrongType.name, allowed: typeLabel } };
    }
  }
  const tooLarge = selected.find((f) => f.size > maxFileSizeMb * 1024 * 1024);
  if (tooLarge) {
    return { ok: false, code: "fileTooLarge", params: { filename: tooLarge.name, maxFileSizeMb } };
  }
  return { ok: true };
}
