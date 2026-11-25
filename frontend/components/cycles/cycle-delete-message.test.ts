import { describe, expect, it } from "vitest";

import { cycleDeleteMessage } from "./cycle-config-manager";

// Fachentscheid 2026-11-25: der Löschdialog eines Zyklus nennt, was per Kaskade mitgeht.
const t = (key: string, values?: Record<string, string | number | Date>) => (values ? `${key}:${JSON.stringify(values)}` : key);

describe("cycleDeleteMessage", () => {
  it("nennt Tabellenstände, Paket-Zuordnungen und Alben samt Fotos", () => {
    const message = cycleDeleteMessage(t, { table_snapshot_count: 2, task_package_count: 1, album_count: 1, album_photo_count: 40 });
    expect(message).toContain("deleteConfirm");
    expect(message).toContain('deleteImpact:{"snapshots":2,"packages":1,"albums":1,"photos":40}');
  });

  it("ohne Folgen nur die Rückfrage", () => {
    expect(cycleDeleteMessage(t, { table_snapshot_count: 0, task_package_count: 0, album_count: 0, album_photo_count: 0 })).toBe("deleteConfirm");
  });

  it("warnt allgemein, wenn die Abfrage scheitert", () => {
    expect(cycleDeleteMessage(t, null)).toBe("deleteConfirm deleteImpactUnknown");
  });
});
