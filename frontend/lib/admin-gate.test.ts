import { describe, expect, it } from "vitest";

import { adminAllowedOnHost, adminGateForwardHeaders, frontendRole, isAdminApiPath, isAdminPagePath, isInternalApiTarget } from "./admin-gate";

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
    const internal = "http://backend:8000";
    expect(adminGateForwardHeaders(new Headers({ host: "app.example.ch" }), internal)).toEqual({});
    expect(adminGateForwardHeaders(new Headers({ host: "admin.example.ch", "x-hocx-admin-gate": "g" }), internal)).toEqual({
      "x-hocx-admin-gate": "g",
      "x-forwarded-host": "admin.example.ch"
    });
  });

  it("reicht den Gate-Header nie an ein öffentliches Ziel oder aus dem öffentlichen Frontend weiter (Review L2/M3)", () => {
    const incoming = new Headers({ host: "admin.example.ch", "x-hocx-admin-gate": "g" });
    expect(adminGateForwardHeaders(incoming, "https://app.example.ch")).toEqual({});
    expect(adminGateForwardHeaders(incoming, "http://backend:8000", "public")).toEqual({});
    expect(adminGateForwardHeaders(incoming, "http://backend:8000", "admin")).toHaveProperty("x-hocx-admin-gate", "g");
    expect(isInternalApiTarget("http://backend:8000")).toBe(true);
    expect(isInternalApiTarget("http://localhost:8000")).toBe(true);
    expect(isInternalApiTarget("http://127.0.0.1:8000")).toBe(true);
    expect(isInternalApiTarget("https://api.example.ch")).toBe(false);
    expect(isInternalApiTarget("kaputt")).toBe(false);
    expect(frontendRole("public")).toBe("public");
    expect(frontendRole("admin")).toBe("admin");
    expect(frontendRole("irgendwas")).toBeUndefined();
  });
});
