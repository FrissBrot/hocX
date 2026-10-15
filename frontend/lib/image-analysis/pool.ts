// Analysiert viele Dateien mit begrenzter Parallelität, Fortschritt und Abbruch. Bevorzugt Web
// Worker; ohne Worker-Unterstützung (ältere Browser, Tests) läuft dieselbe Analyse im
// Hauptthread, ebenfalls nacheinander begrenzt, damit nie viele Dateien gleichzeitig im Speicher
// liegen.

import { analyzeFile, AnalyzableFile, FileAnalysis } from "./analyze";

export type AnalysisProgress = { done: number; total: number };

type Pending = { resolve: (result: FileAnalysis) => void; reject: (error: unknown) => void };

const DEFAULT_CONCURRENCY = 2;

function createWorker(): Worker | null {
  if (typeof Worker === "undefined") return null;
  try {
    return new Worker(new URL("./image-analysis.worker.ts", import.meta.url), { type: "module" });
  } catch {
    return null;
  }
}

class WorkerSlot {
  private pending = new Map<number, Pending>();
  private nextId = 0;

  constructor(private readonly worker: Worker) {
    worker.onmessage = (event: MessageEvent<{ id: number; result?: FileAnalysis; error?: string }>) => {
      const entry = this.pending.get(event.data.id);
      if (!entry) return;
      this.pending.delete(event.data.id);
      if (event.data.result) entry.resolve(event.data.result);
      else entry.reject(new Error(event.data.error ?? "analysis failed"));
    };
    worker.onerror = () => {
      for (const entry of this.pending.values()) entry.reject(new Error("worker failed"));
      this.pending.clear();
    };
  }

  analyze(file: File): Promise<FileAnalysis> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, file });
    });
  }

  terminate() {
    this.worker.terminate();
    for (const entry of this.pending.values()) entry.reject(new DOMException("aborted", "AbortError"));
    this.pending.clear();
  }
}

const UNSUPPORTED: FileAnalysis = { kind: "image", sha256: null, analysis: "failed", format: null, captureDate: "unknown", metadata: {} };

/** Analysiert `files` und liefert die Ergebnisse in derselben Reihenfolge. Ein Fehler bei einer
 * Datei wird zu analysis "failed" (nie ein Abbruch des Ganzen); `signal` bricht alles ab. */
export async function analyzeFiles(
  files: AnalyzableFile[],
  options: { signal?: AbortSignal; concurrency?: number; onProgress?: (progress: AnalysisProgress) => void; onResult?: (index: number, result: FileAnalysis) => void } = {},
): Promise<FileAnalysis[]> {
  const concurrency = Math.max(1, Math.min(options.concurrency ?? DEFAULT_CONCURRENCY, files.length || 1));
  const results: FileAnalysis[] = new Array(files.length);
  let next = 0;
  let done = 0;
  const slots: (WorkerSlot | null)[] = Array.from({ length: concurrency }, () => {
    const worker = createWorker();
    return worker ? new WorkerSlot(worker) : null;
  });
  const abort = () => slots.forEach((slot) => slot?.terminate());
  options.signal?.addEventListener("abort", abort, { once: true });

  async function run(slot: WorkerSlot | null) {
    while (next < files.length) {
      if (options.signal?.aborted) throw new DOMException("aborted", "AbortError");
      const index = next++;
      const file = files[index];
      let result: FileAnalysis;
      try {
        result = slot && file instanceof File ? await slot.analyze(file) : await analyzeFile(file);
      } catch (error) {
        if (options.signal?.aborted) throw error;
        // Worker-Fehler: einmal im Hauptthread versuchen, sonst "nicht prüfbar".
        result = await analyzeFile(file).catch(() => ({ ...UNSUPPORTED, kind: "image" as const }));
      }
      results[index] = result;
      done++;
      options.onResult?.(index, result);
      options.onProgress?.({ done, total: files.length });
    }
  }

  try {
    await Promise.all(slots.map((slot) => run(slot)));
  } finally {
    options.signal?.removeEventListener("abort", abort);
    slots.forEach((slot) => slot?.terminate());
  }
  return results;
}
