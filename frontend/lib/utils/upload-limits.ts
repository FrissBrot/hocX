export const PHOTO_MAX_BYTES = 100 * 1024 ** 2;
export const PHOTO_ZIP_MAX_BYTES = 10 * 1024 ** 3;
export const PHOTO_MAX_FILES = 50;
// Traefik bricht Requests nach 1 h ab (readTimeout, MAIN-OPS-013) - länger zu warten bringt nichts.
export const PHOTO_UPLOAD_TIMEOUT_MS = 60 * 60 * 1000;
// Ab dieser Grösse kann ein ZIP bei langsamer Leitung (unter ~5 Mbit/s) die Stunde überschreiten.
export const PHOTO_ZIP_SLOW_LINE_WARNING_BYTES = 2 * 1024 ** 3;

export function hasLargeZip(files: File[]): boolean {
  return files.some((file) => file.name.toLowerCase().endsWith(".zip") && file.size > PHOTO_ZIP_SLOW_LINE_WARNING_BYTES);
}

export function photoUploadProblem(files: File[], clipIndexes: Set<number>): string | null {
  if (files.length > PHOTO_MAX_FILES) return "Maximal 50 Dateien pro Upload. Für grössere Sammlungen bitte ein ZIP verwenden.";
  if (files.reduce((sum, file) => sum + file.size, 0) > PHOTO_ZIP_MAX_BYTES) return "Ein Upload darf insgesamt maximal 10 GiB gross sein.";
  for (const [index, file] of files.entries()) {
    const max = /\.zip$/i.test(file.name) ? PHOTO_ZIP_MAX_BYTES : clipIndexes.has(index) ? 30 * 1024 ** 2 : PHOTO_MAX_BYTES;
    if (file.size > max) return `„${file.name}“ ist zu gross (maximal ${max / 1024 ** 2} MiB).`;
  }
  return null;
}
