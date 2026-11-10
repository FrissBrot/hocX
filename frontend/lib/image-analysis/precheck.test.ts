import { describe, expect, it } from "vitest";

import type { FileAnalysis } from "./analyze";
import { fileMetadataHints } from "./precheck";

function analysis(format: FileAnalysis["format"], sha: string): FileAnalysis {
  return {
    kind: "image",
    sha256: sha.repeat(64),
    analysis: "ok",
    format,
    captureDate: "present",
    metadata: { taken_at: "2024-05-01T10:00:00", gps: { latitude: 47.1, longitude: 8.2 } },
  };
}

describe("fileMetadataHints (IMGMETA-004)", () => {
  it("schickt für JPEG/PNG/WebP keine Browser-Hinweise (der Server liest die Datei selbst)", () => {
    expect(fileMetadataHints([analysis("jpeg", "a"), analysis("png", "b"), analysis("webp", "c")])).toBeNull();
  });

  it("schickt Hinweise nur für HEIC/HEIF-Dateien", () => {
    const hints = JSON.parse(fileMetadataHints([analysis("jpeg", "a"), analysis("heic", "b")]) ?? "[]");
    expect(hints).toHaveLength(1);
    expect(hints[0].sha256).toBe("b".repeat(64));
    expect(hints[0].metadata.gps).toEqual({ latitude: 47.1, longitude: 8.2 });
  });
});
