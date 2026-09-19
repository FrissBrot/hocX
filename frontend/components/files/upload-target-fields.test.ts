import { describe, expect, it } from "vitest";

import { findUploadRuleProblems, UploadRules } from "./upload-target-fields";

const file = (name: string, bytes = 10) => new File([new Uint8Array(bytes)], name);
const rules = (overrides: Partial<UploadRules> = {}): UploadRules => ({
  allowedExtensions: ["pdf", "jpg"],
  maxFileSizeMb: 1,
  maxFiles: 2,
  ...overrides,
});

describe("findUploadRuleProblems", () => {
  it("finds nothing without an Abgabe (no rules)", () => {
    expect(findUploadRuleProblems([file("x.exe")], null)).toEqual([]);
  });

  it("accepts files that satisfy type, size and count", () => {
    expect(findUploadRuleProblems([file("a.pdf"), file("B.JPG")], rules())).toEqual([]);
  });

  it("names every file with a type the Abgabe does not allow", () => {
    expect(findUploadRuleProblems([file("a.pdf"), file("liste.csv")], rules())).toEqual([
      "liste.csv: Dateityp '.csv' nicht erlaubt",
    ]);
  });

  it("allows any type when the Abgabe lists none", () => {
    expect(findUploadRuleProblems([file("liste.csv")], rules({ allowedExtensions: [] }))).toEqual([]);
  });

  it("flags files over the per-file size limit", () => {
    expect(findUploadRuleProblems([file("gross.pdf", 1024 * 1024 + 1)], rules())).toEqual([
      "gross.pdf: zu gross (max. 1 MB)",
    ]);
  });

  it("flags a queue longer than max files per element, and treats null as unlimited", () => {
    const three = [file("a.pdf"), file("b.pdf"), file("c.pdf")];
    expect(findUploadRuleProblems(three, rules())).toEqual(["Maximal 2 Dateien pro Element erlaubt (3 gewählt)"]);
    expect(findUploadRuleProblems(three, rules({ maxFiles: null }))).toEqual([]);
  });

  it("exempts a ZIP carrier from type and size rules in the photo window only", () => {
    const zip = file("fotos.zip", 5 * 1024 * 1024);
    expect(findUploadRuleProblems([zip], rules(), true)).toEqual([]);
    expect(findUploadRuleProblems([zip], rules(), false)).toHaveLength(1);
  });
});
