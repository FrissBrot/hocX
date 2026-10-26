import { describe, expect, it } from "vitest";

import { can, canAny, expandPermissions, minimalPermissions, roleName, rolesLabel } from "@/lib/permissions";
import { PERMISSION_KEYS, SYSTEM_ROLE_PERMISSIONS } from "@/lib/permissions.generated";

const session = (permissions: string[], features: string[] = []) => ({
  permissions,
  current_tenant: { id: "t", name: "T", profile_image_path: null, profile_image_url: null, enabled_features: features },
});

describe("can", () => {
  it("verlangt die Berechtigung und - falls gebunden - das gebuchte Modul", () => {
    expect(can(session(["finances.manage"], ["finance"]), "finances.manage")).toBe(true);
    expect(can(session(["finances.manage"], []), "finances.manage")).toBe(false);
    expect(can(session([], ["finance"]), "finances.manage")).toBe(false);
    expect(can(session(["meetings.edit"]), "meetings.edit")).toBe(true);
    expect(can(null, "meetings.read")).toBe(false);
  });

  it("canAny reicht eine von mehreren", () => {
    expect(canAny(session(["meetings.edit"]), "participants.manage", "meetings.edit")).toBe(true);
    expect(canAny(session(["meetings.read"]), "participants.manage", "meetings.edit")).toBe(false);
  });
});

describe("Implikationen", () => {
  it("ergänzen wie im Backend und die Standardrollen sind bereits vollständig", () => {
    expect([...expandPermissions(["meetings.edit"])].sort()).toEqual(["meetings.edit", "meetings.read", "meetings.read_drafts"]);
    for (const permissions of Object.values(SYSTEM_ROLE_PERMISSIONS)) {
      expect(expandPermissions(permissions).size).toBe(new Set(permissions).size);
    }
    expect(new Set(SYSTEM_ROLE_PERMISSIONS.admin)).toEqual(new Set(PERMISSION_KEYS));
  });

  it("minimalPermissions entfernt, was aus anderen folgt", () => {
    expect([...minimalPermissions(["meetings.read", "meetings.read_drafts", "meetings.edit", "finances.read"])].sort()).toEqual(["finances.read", "meetings.edit"]);
    expect(expandPermissions(minimalPermissions(SYSTEM_ROLE_PERMISSIONS.writer))).toEqual(new Set(SYSTEM_ROLE_PERMISSIONS.writer));
  });
});

describe("Rollennamen", () => {
  const t = (key: string) => `[${key}]`;
  it("eigener Name vor Standardbezeichnung, mehrere alphabetisch", () => {
    expect(roleName({ name: "Revisor", system_key: null }, t)).toBe("Revisor");
    expect(roleName({ name: null, system_key: "reader" }, t)).toBe("[roles.reader]");
    expect(rolesLabel([{ name: "Zeta", system_key: null }, { name: "Alpha", system_key: "writer" }], t)).toBe("Alpha, Zeta");
  });
});
