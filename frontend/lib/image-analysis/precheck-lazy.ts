// Schlanker Einstieg für den Protokoll-Editor: Bild-Analyse (eigener EXIF-/HEIC-Parser, SHA-256)
// wird erst beim Hochladen eines Bildes geladen, nicht mit dem Editor (Performance-Audit
// Protokoll-Editor 2026-11-22). Verhalten wie isAlreadyUploaded: jeder Fehler -> false (normal
// hochladen, der Server prüft selbst) - auch wenn der Code nicht nachgeladen werden kann.
import type { PrecheckContext } from "./precheck";

export async function isAlreadyUploadedLazy(file: File, context: PrecheckContext): Promise<boolean> {
  try {
    const { isAlreadyUploaded } = await import("./precheck");
    return await isAlreadyUploaded(file, context);
  } catch {
    return false;
  }
}
