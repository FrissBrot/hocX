import { afterEach, describe, expect, it, vi } from "vitest";

import { AbgabeboxUnavailableError, getAssignmentDetail, listAssignments } from "./api";

function respond(status: number, body: unknown = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

describe("Abgabebox-API (Audit MAIN-FE-012)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("meldet 404 weiterhin als nicht gefunden", async () => {
    respond(404);
    await expect(listAssignments("tok")).resolves.toEqual({ status: "not_found" });
    await expect(getAssignmentDetail("tok", "a")).resolves.toBeNull();
  });

  it("unterscheidet das gesperrte Feature (403)", async () => {
    respond(403);
    await expect(listAssignments("tok")).resolves.toEqual({ status: "feature_disabled" });
  });

  it.each([500, 502, 503, 429])("wirft bei voruebergehender Stoerung (%i) statt notFound", async (status) => {
    respond(status);
    await expect(listAssignments("tok")).rejects.toBeInstanceOf(AbgabeboxUnavailableError);
    await expect(getAssignmentDetail("tok", "a")).rejects.toBeInstanceOf(AbgabeboxUnavailableError);
  });

  it("liefert bei Erfolg die Daten", async () => {
    respond(200, [{ public_slug: "a", title: "A", description: null }]);
    await expect(listAssignments("tok")).resolves.toMatchObject({ status: "ok", data: [{ public_slug: "a" }] });
  });
});
