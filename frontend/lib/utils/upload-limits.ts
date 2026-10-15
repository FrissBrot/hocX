export const PHOTO_MAX_BYTES = 100 * 1024 ** 2;
export const PHOTO_ZIP_MAX_BYTES = 10 * 1024 ** 3;
// Ein Upload-Auftrag (Request) des Servers fasst höchstens 50 Dateien bzw. 10 GiB - grössere
// Auswahlen (z. B. ganze Ordner) teilt das Upload-Popup automatisch in mehrere Aufträge auf
// (siehe splitIntoBatches). Die Grenzen unten gelten für die gesamte Auswahl.
export const PHOTO_MAX_FILES = 50;
export const PHOTO_SELECTION_MAX_FILES = 2000;
export const PHOTO_SELECTION_MAX_BYTES = 50 * 1024 ** 3;
export const PHOTO_UPLOAD_TIMEOUT_MS = 3 * 60 * 60 * 1000;

export function photoUploadProblem(files: File[], clipIndexes: Set<number>): string | null {
  if (files.length > PHOTO_SELECTION_MAX_FILES) return "Maximal 2000 Dateien pro Auswahl. Für grössere Sammlungen bitte ein ZIP verwenden.";
  if (files.reduce((sum, file) => sum + file.size, 0) > PHOTO_SELECTION_MAX_BYTES) return "Eine Auswahl darf insgesamt maximal 50 GiB gross sein.";
  for (const [index, file] of files.entries()) {
    const max = /\.zip$/i.test(file.name) ? PHOTO_ZIP_MAX_BYTES : clipIndexes.has(index) ? 30 * 1024 ** 2 : PHOTO_MAX_BYTES;
    if (file.size > max) return `„${file.name}“ ist zu gross (maximal ${max >= 1024 ** 3 ? `${max / 1024 ** 3} GiB` : `${max / 1024 ** 2} MiB`}).`;
  }
  return null;
}
