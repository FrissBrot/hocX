import { describe, expect, it } from "vitest";

import { adminAllowedOnHost, adminGateForwardHeaders, isAdminApiPath, isAdminPagePath } from "./admin-gate";

describe("admin-gate (SEC-AUTH-001)", () => {
  it("erkennt Admin-Seiten und Admin-API nur am ganzen Pfadsegment", () => {
    expect(isAdminPagePath("/admin")).toBe(true);
    expect(isAdminPagePath("/admin/login")).toBe(true);
    expect(isAdminPagePath("/administration")).toBe(false);
    expect(isAdminApiPath("/api/admin/auth/session")).toBe(true);
    expect(isAdminApiPath("/api/admin?x=1")).toBe(true);
    expect(isAdminApiPath("/api/administration")).toBe(false);
    expect(isAdminApiPath("/api/auth/session")).toBe(false);
  });

  it("erlaubt Admin-Seiten nur auf der Admin-Domain, ohne Konfiguration überall", () => {
    expect(adminAllowedOnHost("admin.example.ch", "admin.example.ch")).toBe(true);
    expect(adminAllowedOnHost("ADMIN.example.ch:8443", "admin.example.ch")).toBe(true);
    expect(adminAllowedOnHost("app.example.ch", "admin.example.ch")).toBe(false);
    expect(adminAllowedOnHost("evil.admin.example.ch", "admin.example.ch")).toBe(false);
    expect(adminAllowedOnHost(null, "admin.example.ch")).toBe(false);
    expect(adminAllowedOnHost("app.example.ch", undefined)).toBe(true);
    expect(adminAllowedOnHost("app.example.ch", "")).toBe(true);
  });

  it("reicht Gate-Header und Host nur weiter, wenn Traefik den Gate-Header gesetzt hat", () => {
    expect(adminGateForwardHeaders(new Headers({ host: "app.example.ch" }))).toEqual({});
    expect(adminGateForwardHeaders(new Headers({ host: "admin.example.ch", "x-hocx-admin-gate": "g" }))).toEqual({
      "x-hocx-admin-gate": "g",
      "x-forwarded-host": "admin.example.ch"
    });
  });
});
