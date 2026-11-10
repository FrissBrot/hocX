import { describe, expect, it } from "vitest";

import { filesFromDataTransfer } from "./folder-files";

function transfer(files: File[], entries: unknown[]): DataTransfer {
  let protectedAfterDrop = false;
  const dataTransfer = {
    // Wie in Chromium: nach dem drop-Event ist die Dateiliste leer.
    get files() {
      return protectedAfterDrop ? [] : files;
    },
    items: entries.map((entry) => ({ webkitGetAsEntry: () => entry })),
  } as unknown as DataTransfer;
  queueMicrotask(() => {
    protectedAfterDrop = true;
  });
  return dataTransfer;
}

describe("filesFromDataTransfer (IMGMETA-014)", () => {
  it("meldet direkt gezogene Dateien nicht als Ordner, auch wenn der DataTransfer danach leer ist", async () => {
    const files = [new File(["a"], "a.jpg"), new File(["b"], "notiz.txt")];
    const result = await filesFromDataTransfer(transfer(files, files.map((file) => ({ isFile: true, isDirectory: false, name: file.name }))));
    expect(result.fromFolder).toBe(false);
    expect(result.files.map((file) => file.name)).toEqual(["a.jpg", "notiz.txt"]);
  });

  it("klappt Ordner auf und meldet fromFolder", async () => {
    const inner = new File(["x"], "bild.jpg");
    const folder = {
      isFile: false,
      isDirectory: true,
      name: "Ferien",
      createReader: () => {
        let done = false;
        return {
          readEntries: (success: (entries: unknown[]) => void) => {
            success(done ? [] : [{ isFile: true, isDirectory: false, name: "bild.jpg", file: (ok: (file: File) => void) => ok(inner) }]);
            done = true;
          },
        };
      },
    };
    const result = await filesFromDataTransfer(transfer([], [folder]));
    expect(result).toEqual({ files: [inner], fromFolder: true });
  });
});
