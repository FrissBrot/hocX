import { afterEach, describe, expect, it, vi } from "vitest";

import {
  classifyResult,
  isSiteDocument,
  parseDocumentId,
  parseHashFragment,
  redirectTarget,
  sha256Hex,
  shortDocumentId,
  verifyHash,
  type VerifySite,
} from "./verify";

const DOC_ID = "0192f0aa-0000-7000-8000-00007f3a91c2";

describe("sha256Hex", () => {
  it("berechnet den SHA-256 lokal (Web Crypto)", async () => {
    const data = new TextEncoder().encode("abc").buffer as ArrayBuffer;
    expect(await sha256Hex(data)).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("ein geändertes Byte ergibt einen anderen Hash", async () => {
    const original = new TextEncoder().encode("%PDF-1.7 hocX");
    const changed = original.slice();
    changed[changed.length - 1] ^= 1;
    expect(await sha256Hex(original.buffer as ArrayBuffer)).not.toBe(await sha256Hex(changed.buffer as ArrayBuffer));
  });
});

describe("parseDocumentId / shortDocumentId", () => {
  it("akzeptiert nur UUIDs aus dem QR-Code", () => {
    expect(parseDocumentId(DOC_ID.toUpperCase())).toBe(DOC_ID);
    expect(parseDocumentId([DOC_ID, "x"])).toBe(DOC_ID);
    expect(parseDocumentId("verify")).toBeNull();
    expect(parseDocumentId("<script>")).toBeNull();
    expect(parseDocumentId(undefined)).toBeNull();
  });

  it("zeigt die Kurz-ID wie im PDF", () => {
    expect(shortDocumentId(DOC_ID)).toBe("7F3A-91C2");
  });
});

describe("classifyResult", () => {
  const base = { found: true, document_id: DOC_ID, document_type: "protocol", created_at: "2026-05-01T10:00:00Z" };

  it("nicht gefunden", () => {
    expect(classifyResult({ found: false })).toEqual({ kind: "not_found" });
  });

  it("Original ohne freigegebene Identität", () => {
    const outcome = classifyResult(base);
    expect(outcome).toMatchObject({ kind: "original", identity: "anonymous", otherDocument: false, newerVersion: null });
  });

  it("Name ohne Bestätigung und Name mit Bestätigung", () => {
    expect(classifyResult({ ...base, tenant_name: "Verein", organization_verified: false })).toMatchObject({ identity: "named" });
    expect(classifyResult({ ...base, tenant_name: "Verein", organization_verified: true })).toMatchObject({ identity: "verified" });
    // Abzeichen ohne freigegebenen Namen gibt es nicht
    expect(classifyResult({ ...base, organization_verified: true })).toMatchObject({ identity: "anonymous" });
  });

  it("neuere Version und fremder QR-Code", () => {
    expect(classifyResult({ ...base, is_superseded: true, latest_version_label: "v1.3" })).toMatchObject({ newerVersion: "v1.3" });
    expect(classifyResult({ ...base, is_superseded: false, latest_version_label: "v1.3" })).toMatchObject({ newerVersion: null });
    expect(classifyResult({ ...base, document_id_matches: false })).toMatchObject({ otherDocument: true });
  });

  it("importierter, nicht verifizierter Eintrag (TYPST-007)", () => {
    expect(classifyResult(base)).toMatchObject({ importUnverified: false });
    expect(classifyResult({ ...base, import_unverified: true })).toMatchObject({ importUnverified: true });
  });

  it("überschriebener Titel (STUDIO-007)", () => {
    expect(classifyResult(base)).toMatchObject({ titleOverridden: false });
    expect(classifyResult({ ...base, title_overridden: true })).toMatchObject({ titleOverridden: true });
  });
});

describe("verifyHash", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("schickt nur Hash und Dokument-ID, ohne Cookies", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ found: false }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await verifyHash("a".repeat(64), DOC_ID);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/public/verify");
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(init.body)).toEqual({ sha256: "a".repeat(64), document_id: DOC_ID });
    await verifyHash("b".repeat(64), null);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ sha256: "b".repeat(64) });
  });

  it("wirft bei Serverfehlern", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(verifyHash("a".repeat(64), null)).rejects.toThrow("verify 503");
  });
});

describe("Prüf-Domains der Mandanten", () => {
  const SHA = "a".repeat(64);
  const own = "11111111-1111-4111-8111-111111111111";
  const other = "22222222-2222-4222-8222-222222222222";
  const site: VerifySite = { domain: "verify.tv-seedorf.ch", tenant_name: "TV Seedorf", tenant_public_id: own, central_verify_url: "https://abgabe.hocx.ch/verify" };
  const found = (tenant: string, verifyDomain?: string) => ({ found: true, tenant_name: "X", tenant_public_id: tenant, verify_domain: verifyDomain });

  it("liest nur einen gültigen Hash aus dem Fragment", () => {
    expect(parseHashFragment(`#sha256=${SHA}`)).toBe(SHA);
    expect(parseHashFragment(`#sha256=${SHA.toUpperCase()}`)).toBe(SHA);
    expect(parseHashFragment("#sha256=abc")).toBeNull();
    expect(parseHashFragment(`#x=${SHA}`)).toBeNull();
    expect(parseHashFragment("")).toBeNull();
  });

  it("zentrale Seite leitet zur Prüf-Domain des Ausstellers weiter, Hash im Fragment", () => {
    const target = redirectTarget(found(own, "verify.tv-seedorf.ch"), { currentHost: "abgabe.hocx.ch", site: null, documentId: DOC_ID, sha256: SHA });
    expect(target).toEqual({ kind: "tenant", domain: "verify.tv-seedorf.ch", url: `https://verify.tv-seedorf.ch/verify?id=${DOC_ID}#sha256=${SHA}` });
  });

  it("ohne Prüf-Domain oder nicht gefunden: keine Weiterleitung", () => {
    expect(redirectTarget(found(own), { currentHost: "abgabe.hocx.ch", site: null, documentId: null, sha256: SHA })).toBeNull();
    expect(redirectTarget({ found: false }, { currentHost: "abgabe.hocx.ch", site, documentId: null, sha256: SHA })).toBeNull();
  });

  it("eigene Dokumente bleiben auf der Prüfseite des Mandanten (keine Schleife)", () => {
    const result = found(own, "verify.tv-seedorf.ch");
    expect(isSiteDocument(result, site)).toBe(true);
    expect(redirectTarget(result, { currentHost: "verify.tv-seedorf.ch", site, documentId: null, sha256: SHA })).toBeNull();
  });

  it("fremde Dokumente: zur Prüf-Domain des richtigen Mandanten, sonst zu hocX", () => {
    expect(redirectTarget(found(other, "verify.fc-beispiel.ch"), { currentHost: "verify.tv-seedorf.ch", site, documentId: null, sha256: SHA })).toEqual({
      kind: "tenant",
      domain: "verify.fc-beispiel.ch",
      url: `https://verify.fc-beispiel.ch/verify#sha256=${SHA}`,
    });
    expect(redirectTarget(found(other), { currentHost: "verify.tv-seedorf.ch", site, documentId: null, sha256: SHA })).toEqual({
      kind: "central",
      url: `https://abgabe.hocx.ch/verify#sha256=${SHA}`,
    });
    // anonym ausgestellt (keine Mandanten-ID freigegeben): ebenfalls nicht von diesem Mandanten
    expect(redirectTarget({ found: true }, { currentHost: "verify.tv-seedorf.ch", site, documentId: null, sha256: SHA })?.kind).toBe("central");
  });
});
