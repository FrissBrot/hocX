import { describe, expect, it } from "vitest";

import { resolveScopes, seesAll } from "@/lib/permissions";

// Gleiche Fälle wie backend/tests/test_permissions_phase4.py::test_resolve_scopes
describe("resolveScopes", () => {
  it("vererbt die Reichweite an implizierte Rechte", () => {
    const scopes = resolveScopes(["submissions.review"], { "submissions.review": "assigned" });
    expect(scopes.get("submissions.review")).toBe("assigned");
    expect(scopes.get("submissions.read")).toBe("assigned");
  });

  it("ein Recht ohne Reichweite impliziert «alle»", () => {
    const scopes = resolveScopes(["submissions.review", "submissions.manage"], { "submissions.review": "assigned" });
    expect(scopes.get("submissions.review")).toBe("assigned");
    expect(scopes.get("submissions.read")).toBe("all");
  });

  it("ohne Angabe gilt «alle», eigene Angabe «alle» gewinnt", () => {
    expect(resolveScopes(["submissions.review"], {}).get("submissions.read")).toBe("all");
    const scopes = resolveScopes(["submissions.review"], { "submissions.review": "assigned", "submissions.read": "all" });
    expect(scopes.get("submissions.read")).toBe("all");
  });
});

describe("seesAll", () => {
  it("liest assigned_only aus der Sitzung", () => {
    expect(seesAll({ assigned_only: ["submissions.read"] }, "submissions.read")).toBe(false);
    expect(seesAll({ assigned_only: [] }, "submissions.read")).toBe(true);
    expect(seesAll(null, "submissions.read")).toBe(true);
  });
});
