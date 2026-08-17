// Extracted from upload-form.tsx (audit A5, 2026-08-16) so the client-side file validation
// - the reviewer's only defense before a request goes out from this unauthenticated public
// form - is a plain, unit-testable function instead of logic only reachable by rendering the
// whole component. Server-side validation is still authoritative (see abgabebox-backend); this
// is purely the first line of feedback for the person uploading.

export type UploadValidationResult = { ok: true } | { ok: false; error: string };

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
  // maxFiles = null bedeutet unbegrenzt viele Dateien (siehe Admin-Bereich, Feld "Max.
  // Dateien" leer gelassen). Das Limit gilt kumulativ ueber alle bisherigen Uploads dieses
  // Elements hinweg, nicht nur fuer diese eine Auswahl - siehe alreadyUploaded.
  if (maxFiles !== null) {
    const remaining = Math.max(0, maxFiles - alreadyUploaded);
    if (selected.length > remaining) {
      return {
        ok: false,
        error: `Maximal ${maxFiles} Datei(en) insgesamt erlaubt (${remaining} noch möglich)`,
      };
    }
  }
  if (allowedFileTypes.length > 0) {
    const allowed = allowedFileTypes.map((t) => t.toLowerCase());
    const typeLabel = allowedFileTypes.map((t) => t.toUpperCase()).join(", ");
    const wrongType = selected.find((f) => !allowed.includes(getExtension(f.name)));
    if (wrongType) {
      return { ok: false, error: `„${wrongType.name}" hat ein nicht erlaubtes Dateiformat (erlaubt: ${typeLabel})` };
    }
  }
  const tooLarge = selected.find((f) => f.size > maxFileSizeMb * 1024 * 1024);
  if (tooLarge) {
    return { ok: false, error: `„${tooLarge.name}" ist zu gross (max. ${maxFileSizeMb} MB)` };
  }
  return { ok: true };
}
