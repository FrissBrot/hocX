import { describe, expect, it } from "vitest";

import { activeAdminGroupId, adminBreadcrumb, attentionItems, buildAdminNav, findActiveAdminLink, groupCount, linkCount, linkStatus, resolveOpenAdminGroup, toggleAdminGroup } from "./admin-shell-nav";

const hrefs = (role: "owner" | "support") => buildAdminNav(role).flatMap((group) => group.links.map((link) => link.href));

describe("admin-shell-nav", () => {
  it("hat die sieben Bereiche A–G für owner", () => {
    expect(buildAdminNav("owner").map((group) => group.id)).toEqual(["overview", "tenants", "access", "security", "operations", "analytics", "settings"]);
  });

  it("blendet owner-Seiten für support aus und lässt leere Gruppen weg", () => {
    const support = hrefs("support");
    expect(support).not.toContain("/admin/users");
    expect(support).not.toContain("/admin/system");
    expect(support).not.toContain("/admin/security/audit");
    expect(support).toContain("/admin/tenants");
    expect(support).toContain("/admin/security");
    expect(buildAdminNav("support").map((group) => group.id)).not.toContain("access");
  });

  it("führt die Einstellungsseiten (1.5.1); Integrationen und Technik nur für owner", () => {
    expect(hrefs("owner")).toEqual(expect.arrayContaining(["/admin/settings/security", "/admin/settings/integrations", "/admin/settings/system"]));
    expect(hrefs("support")).toContain("/admin/settings/security");
    expect(hrefs("support")).not.toContain("/admin/settings/integrations");
    expect(hrefs("support")).not.toContain("/admin/settings/system");
  });

  it("erkennt den aktiven Eintrag über den längsten Pfad", () => {
    const nav = buildAdminNav("owner");
    expect(findActiveAdminLink(nav, "/admin/security/events")?.link.href).toBe("/admin/security/events");
    expect(findActiveAdminLink(nav, "/admin/security")?.link.href).toBe("/admin/security");
    expect(findActiveAdminLink(nav, "/admin/tenants/abc/users")?.link.href).toBe("/admin/tenants");
    expect(findActiveAdminLink(nav, "/admin")?.link.href).toBe("/admin");
    expect(findActiveAdminLink(nav, "/admin/account")?.link.href).toBe("/admin/account");
  });

  it("baut Brotkrumen mit Bereich und Detailseite", () => {
    const nav = buildAdminNav("owner");
    expect(adminBreadcrumb(nav, "/admin")).toEqual({ groupTitleKey: null, link: null, nested: false });
    const detail = adminBreadcrumb(nav, "/admin/tenants/abc");
    expect(detail.groupTitleKey).toBe("groups.tenants");
    expect(detail.link?.href).toBe("/admin/tenants");
    expect(detail.nested).toBe(true);
    expect(adminBreadcrumb(nav, "/admin/jobs").nested).toBe(false);
  });

  it("zeigt Zähler nur, wenn sie grösser als 0 sind", () => {
    const nav = buildAdminNav("owner");
    const counts = { tenants: 3, verifications_open: 0, security_alerts: 2, operations_problems: null };
    const security = nav.find((group) => group.id === "security")!;
    expect(groupCount(security, counts)).toBe(2);
    expect(groupCount(nav.find((group) => group.id === "operations")!, counts)).toBeNull();
    const verifications = nav.find((group) => group.id === "tenants")!.links.find((link) => link.href === "/admin/verifications")!;
    expect(linkCount(verifications, counts)).toBeNull();
    expect(attentionItems(counts, "owner")).toEqual([{ key: "security_alerts", count: 2, href: "/admin/security/alerts" }]);
    expect(attentionItems(counts, "support")[0].href).toBe("/admin/security");
    expect(attentionItems(null, "owner")).toEqual([]);
  });

  it("zeigt den Backup-Status als Punkt am Eintrag Backups (nur bekannte Werte)", () => {
    const nav = buildAdminNav("support");
    const backups = nav.flatMap((group) => group.links).find((link) => link.href === "/admin/backups")!;
    const base = { tenants: 1, verifications_open: 0, security_alerts: null, operations_problems: null };
    expect(linkStatus(backups, { ...base, backup_status: "critical" })).toBe("critical");
    expect(linkStatus(backups, { ...base, backup_status: null })).toBeNull();
    expect(linkStatus(backups, null)).toBeNull();
    const jobs = nav.flatMap((group) => group.links).find((link) => link.href === "/admin/jobs");
    if (jobs) expect(linkStatus(jobs, { ...base, backup_status: "warning" })).toBeNull();
  });

  describe("einklappbare Bereiche (1.5.1)", () => {
    const nav = buildAdminNav("owner");

    it("öffnet den Bereich der aktiven Seite automatisch, auch auf Detailseiten", () => {
      expect(activeAdminGroupId(nav, "/admin/jobs")).toBe("operations");
      expect(activeAdminGroupId(nav, "/admin/tenants/abc/users")).toBe("tenants");
      expect(resolveOpenAdminGroup(nav, "/admin/security/events", "operations")).toBe("security");
    });

    it("ohne aktiven Bereich gilt der gemerkte, unbekannte oder titellose fallen weg", () => {
      expect(activeAdminGroupId(nav, "/admin")).toBeNull();
      expect(resolveOpenAdminGroup(nav, "/admin", "analytics")).toBe("analytics");
      expect(resolveOpenAdminGroup(nav, "/admin/account", "gibt-es-nicht")).toBeNull();
      expect(resolveOpenAdminGroup(nav, "/admin", "overview")).toBeNull();
      // support sieht «Benutzer & Zugänge» nicht - ein gemerkter Bereich daraus öffnet nichts
      expect(resolveOpenAdminGroup(buildAdminNav("support"), "/admin", "access")).toBeNull();
    });

    it("Klick öffnet einen Bereich und schliesst die anderen (Akkordeon), zweiter Klick schliesst", () => {
      expect(toggleAdminGroup("tenants", "operations")).toBe("operations");
      expect(toggleAdminGroup("operations", "operations")).toBeNull();
      expect(toggleAdminGroup(null, "security")).toBe("security");
    });
  });
});
