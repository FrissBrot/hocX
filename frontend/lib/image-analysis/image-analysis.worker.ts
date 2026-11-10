// Web Worker: hält Hashing und Parsing grosser Bildmengen vom Hauptthread fern, damit das
// Upload-Popup bedienbar bleibt. Protokoll: {id, file} -> {id, result} bzw. {id, error}.

import { analyzeFile } from "./analyze";

type Request = { id: number; file: File };

self.onmessage = async (event: MessageEvent<Request>) => {
  const { id, file } = event.data;
  try {
    const result = await analyzeFile(file);
    (self as unknown as Worker).postMessage({ id, result });
  } catch (error) {
    (self as unknown as Worker).postMessage({ id, error: String(error) });
  }
};
