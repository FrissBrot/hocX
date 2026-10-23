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
