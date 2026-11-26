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
    expect(auditAreaCategories("auth")).toEqual(["user", "mfa", "password", "sessions"]);
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

describe("Verlauf der Organisation: geloggte Aktionen ohne Rohcode", () => {
  it("kennt die Kategorien, die das Backend tatsächlich loggt", async () => {
    const { AUDIT_CATEGORIES } = await import("./audit-labels");
    for (const category of ["agenda_item", "file", "file_import", "finance_settings", "mfa", "password", "photo", "sessions", "submission", "template_element"]) {
      expect(AUDIT_CATEGORIES).toContain(category);
    }
  });

  it("leitet den Vorgang auch aus Endungen wie _create, trashed, enroll, change, revoke_user ab", () => {
    expect(auditVerb("tenant.domain_create")).toBe("created");
    expect(auditVerb("tenant.domain_delete")).toBe("deleted");
    expect(auditVerb("file.trashed")).toBe("deleted");
    expect(auditVerb("file.trash_emptied")).toBe("deleted");
    expect(auditVerb("mfa.remove")).toBe("deleted");
    expect(auditVerb("mfa.enroll")).toBe("created");
    expect(auditVerb("user.invited")).toBe("created");
    expect(auditVerb("file.renamed")).toBe("updated");
    expect(auditVerb("password.change")).toBe("updated");
    expect(auditVerb("user.update_access")).toBe("updated");
    expect(auditVerb("sessions.revoke_user")).toBe("revoked");
    expect(auditVerb("personal_data.export")).toBe("exported");
    expect(auditVerb("tenant.data_export_downloaded")).toBe("exported");
  });
});
