import { describe, expect, it } from "vitest";

import { auditVerb, describeAuditAction } from "./audit-labels";

describe("audit labels", () => {
  it("derives the verb from the action suffix", () => {
    expect(auditVerb("user.login_failed")).toBe("loginFailed");
    expect(auditVerb("user.login")).toBe("login");
    expect(auditVerb("admin.tenant_users_viewed")).toBe("viewed");
    expect(auditVerb("protocol.deleted")).toBe("deleted");
    expect(auditVerb("participant.bulk_deleted")).toBe("deleted");
    expect(auditVerb("fine.collected")).toBe("collected");
    expect(auditVerb("protocol.status_changed")).toBe("updated");
    expect(auditVerb("backup.restore.create")).toBe("created");
  });

  it("combines category and verb, unknown codes stay readable", () => {
    const t = (key: string) => ({ "categories.protocol": "Protokoll", "verbs.deleted": "gelöscht" })[key] ?? key;
    expect(describeAuditAction("protocol.deleted", t)).toBe("Protokoll · gelöscht");
    expect(describeAuditAction("mystery.something_odd", t)).toBe("Mystery · Something odd");
  });
});

describe("Bereiche und Code-Anzeige (Audit-Log 1.5.1)", () => {
  it("ordnet Kategorien zentral Bereichen zu und zählt je Bereich", async () => {
    const { auditArea, countByArea, auditAreaCategories } = await import("./audit-labels");
    expect(auditArea("user.login_failed")).toBe("auth");
    expect(auditArea("todo_fine.tariff_updated")).toBe("finance");
    expect(auditArea("personal_data.viewed")).toBe("privacy");
    expect(auditArea("mystery.x")).toBeNull();
    expect(countByArea({ user: 3, protocol: 2, todo: 1, mystery: 9 })).toEqual({ auth: 3, content: 3, finance: 0, admin: 0, privacy: 0 });
    expect(auditAreaCategories("auth")).toEqual(["user"]);
  });

  it("unbekannte Aktionen erscheinen als Code, bekannte als «Bereich · Verb»", async () => {
    const { auditActionLabel, auditInitials } = await import("./audit-labels");
    const t = (key: string) => ({ "categories.protocol": "Protokoll", "verbs.deleted": "gelöscht" })[key] ?? key;
    expect(auditActionLabel("protocol.deleted", t)).toEqual({ label: "Protokoll · gelöscht", known: true });
    expect(auditActionLabel("mystery.something_odd", t)).toEqual({ label: "mystery.something_odd", known: false });
    expect(auditActionLabel("protocol.frobnicated", t)).toEqual({ label: "protocol.frobnicated", known: false });
    expect(auditInitials("Timo Weber")).toBe("TW");
    expect(auditInitials("admin@example.com")).toBe("A");
    expect(auditInitials(null)).toBe("·");
  });
});
