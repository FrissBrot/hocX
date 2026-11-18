import { describe, expect, it } from "vitest";

import { expandPermissions } from "@/lib/permissions";
import { PERMISSION_KEYS, PERMISSIONS, SYSTEM_ROLE_PERMISSIONS } from "@/lib/permissions.generated";
import { ROLE_TEMPLATES, templateSelection } from "@/lib/role-templates";

const ALL = new Set<string>(PERMISSION_KEYS);
const MFA = new Set(PERMISSIONS.filter((permission) => permission.requiresMfa).map((permission) => permission.key));
const byKey = (key: string) => ROLE_TEMPLATES.find((template) => template.key === key)!;

describe("Rollen-Vorlagen (Phase 7)", () => {
  it("enthält die sechs Vorlagen des Plans", () => {
    expect(ROLE_TEMPLATES.map((template) => template.key)).toEqual(["president", "secretary", "treasurer", "auditor", "reviewer", "member"]);
  });

  it("verlangt keine MFA-Rechte und vergibt keine Administration", () => {
    for (const template of ROLE_TEMPLATES) {
      const permissions = expandPermissions(template.permissions);
      expect([...permissions].filter((key) => MFA.has(key))).toEqual([]);
    }
  });

  it("Revisor ist rein lesend inkl. Finanzen", () => {
    const permissions = expandPermissions(byKey("auditor").permissions);
    expect(permissions.has("finances.read")).toBe(true);
    for (const key of permissions) {
      expect(key).toMatch(/\.(read|read_drafts|personal)$/);
    }
  });

  it("Abgabe-Prüfer: submissions.read + review nur zugewiesene", () => {
    const { selected, scopes, omitted } = templateSelection(byKey("reviewer"), ALL);
    expect(expandPermissions(selected).has("submissions.read")).toBe(true);
    expect(selected.has("submissions.review")).toBe(true);
    expect(scopes).toEqual({ "submissions.read": "assigned", "submissions.review": "assigned" });
    expect(omitted).toEqual([]);
  });

  it("Mitglied entspricht der Standardrolle Leser", () => {
    expect([...expandPermissions(byKey("member").permissions)].sort()).toEqual([...SYSTEM_ROLE_PERMISSIONS.reader].sort());
  });

  it("übernimmt nur eigene Rechte, und eigene «nur zugewiesene» bleiben zugewiesen", () => {
    const own = new Set(["meetings.read", "todos.complete_own", "finances.read", "submissions.read"]);
    const member = templateSelection(byKey("member"), own, new Set(["submissions.read"]));
    expect(member.omitted).toEqual([]);
    expect(member.scopes).toEqual({ "submissions.read": "assigned" });

    const secretary = templateSelection(byKey("secretary"), own);
    expect([...expandPermissions(secretary.selected)].sort()).toEqual(["meetings.read", "todos.complete_own"]);
    expect(secretary.omitted).toContain("meetings.edit");
    expect(secretary.omitted).not.toContain("meetings.read");
  });
});
