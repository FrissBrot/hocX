import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";

import { domainErrorMessage, domainStatus } from "./tenant-domain-row";

const t = (key: string, values?: Record<string, string | number>) => (values ? `${key}:${JSON.stringify(values)}` : key);

describe("domainErrorMessage", () => {
  it("übersetzt Fehlercodes der Domain-Routen statt den deutschen Backend-Text zu zeigen", () => {
    const error = new ApiError("TXT-Record … nicht gefunden", "validation", 400, {
      code: "domain_txt_missing",
      message: "TXT-Record … nicht gefunden",
      record: "_hocx-challenge.app.example.ch",
    });
    expect(domainErrorMessage(error, t, "verifyFailed")).toContain("errors.domain_txt_missing");
    expect(domainErrorMessage(error, t, "verifyFailed")).toContain("_hocx-challenge.app.example.ch");
  });

  it("zeigt bei 429 eine eigene Meldung", () => {
    expect(domainErrorMessage(new ApiError("Too many requests", "validation", 429), t, "verifyFailed")).toBe("errors.rateLimited");
  });

  it("behält unbekannte Fehlertexte", () => {
    expect(domainErrorMessage(new Error("Netzwerk weg"), t, "verifyFailed")).toBe("Netzwerk weg");
  });
});

describe("domainStatus", () => {
  it("liefert den Hinweis für unerreichbare Domains als Text", () => {
    const status = domainStatus(
      {
        id: "1", purpose: "app", domain: "app.example.ch", status: "active", verification_token: "x",
        challenge_record_name: "y", target_host: null, verified_at: null, is_healthy: false, last_checked_at: null,
      },
      t
    );
    expect(status.variant).toBe("danger");
    expect(status.hint).toBe("statusUnreachableHint");
  });
});
