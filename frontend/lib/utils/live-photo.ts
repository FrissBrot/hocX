// Live-Photo-Zuordnung im Browser - spiegelt backend/app/services/apple_media.py (pair_live_clips):
// Ein iPhone-Export liefert IMG_1234.HEIC (Standbild) und IMG_1234.MOV (Clip). Der Clip gehört zum
// Bild mit gleichem Namen ohne Endung (Gross-/Kleinschreibung egal) und ist kein eigenes Foto.

const CLIP_EXTENSIONS = new Set(["mov", "mp4", "m4v"]);
const HEIC_EXTENSIONS = new Set(["heic", "heif"]);

function splitName(name: string): { stem: string; extension: string } {
  const dot = name.lastIndexOf(".");
  if (dot <= 0) return { stem: name.toLowerCase(), extension: "" };
  return { stem: name.slice(0, dot).toLowerCase(), extension: name.slice(dot + 1).toLowerCase() };
}

export function isLiveClipName(name: string): boolean {
  return CLIP_EXTENSIONS.has(splitName(name).extension);
}

export function isHeicName(name: string): boolean {
  return HEIC_EXTENSIONS.has(splitName(name).extension);
}

/** {Index des Bildes → Index des Clips}. Jeder Clip wird höchstens einem Bild zugeordnet. */
export function pairLiveClips(names: string[]): Map<number, number> {
  const clipByStem = new Map<string, number>();
  names.forEach((name, index) => {
    const { stem, extension } = splitName(name);
    if (CLIP_EXTENSIONS.has(extension) && !clipByStem.has(stem)) clipByStem.set(stem, index);
  });
  const pairs = new Map<number, number>();
  names.forEach((name, index) => {
    const { stem, extension } = splitName(name);
    if (CLIP_EXTENSIONS.has(extension)) return;
    const clipIndex = clipByStem.get(stem);
    if (clipIndex === undefined) return;
    clipByStem.delete(stem);
    pairs.set(index, clipIndex);
  });
  return pairs;
}
