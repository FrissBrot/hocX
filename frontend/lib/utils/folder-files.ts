// Ordner per Drag & Drop: sammelt alle Dateien rekursiv (Chrome, Edge, Firefox, Safari über
// webkitGetAsEntry). Versteckte Systemdateien (.DS_Store, __MACOSX) werden übersprungen.

type Entry = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (success: (file: File) => void, failure: (error: unknown) => void) => void;
  createReader?: () => { readEntries: (success: (entries: Entry[]) => void, failure: (error: unknown) => void) => void };
};

function isHidden(name: string): boolean {
  return name.startsWith(".") || name === "__MACOSX" || name === "Thumbs.db";
}

async function readEntry(entry: Entry, out: File[], limit: number): Promise<void> {
  if (out.length >= limit || isHidden(entry.name)) return;
  if (entry.isFile && entry.file) {
    out.push(await new Promise<File>((resolve, reject) => entry.file!(resolve, reject)));
    return;
  }
  if (!entry.isDirectory || !entry.createReader) return;
  const reader = entry.createReader();
  // readEntries liefert in Blöcken (Chrome: 100) - bis zur leeren Antwort weiterlesen.
  for (;;) {
    const batch = await new Promise<Entry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    for (const child of batch) await readEntry(child, out, limit);
    if (out.length >= limit) break;
  }
}

/** Dateien eines Drops - Ordner werden aufgeklappt. Ohne Entry-API die normale Dateiliste. */
export async function filesFromDataTransfer(dataTransfer: DataTransfer, limit = 5000): Promise<File[]> {
  const items = Array.from(dataTransfer.items ?? []);
  const entries: Entry[] = [];
  for (const item of items) {
    const entry = (item.webkitGetAsEntry?.() ?? null) as unknown as Entry | null;
    if (entry) entries.push(entry);
  }
  if (!entries.length || !entries.some((entry) => entry.isDirectory)) return Array.from(dataTransfer.files);
  const out: File[] = [];
  for (const entry of entries) await readEntry(entry, out, limit);
  return out;
}

/** Nur Dateien, die der Galerie-Upload annimmt (Bilder, HEIC, Live-Clips, ZIP) - Ordner
 * enthalten oft Begleitdateien (XMP-Sidecars, Videos, Dokumente). */
export function isGalleryCandidate(file: File): boolean {
  if (file.type.startsWith("image/")) return true;
  return /\.(jpe?g|png|gif|webp|bmp|tiff?|heic|heif|mov|zip)$/i.test(file.name);
}
