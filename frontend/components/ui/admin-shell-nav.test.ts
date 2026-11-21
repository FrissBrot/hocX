import { describe, expect, it } from "vitest";

import { adminBreadcrumb, attentionItems, buildAdminNav, findActiveAdminLink, groupCount, linkCount } from "./admin-shell-nav";

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
});
