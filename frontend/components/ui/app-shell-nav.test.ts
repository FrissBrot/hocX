import { describe, expect, it } from "vitest";

import { buildNav, formatRoleLabel, isNavLinkActive, relatedNavLink, SETTINGS_GROUP } from "./app-shell-nav";
import { locales } from "@/i18n/locale-config.generated";
import deNav from "@/messages/de/nav.json";
import enNav from "@/messages/en/nav.json";
import frNav from "@/messages/fr/nav.json";
import itNav from "@/messages/it/nav.json";
import { SYSTEM_ROLE_PERMISSIONS, type SystemRoleKey } from "@/lib/permissions.generated";
import type { SessionInfo } from "@/types/api";

const CATALOGS: Record<string, Record<string, unknown>> = { de: deNav, en: enNav, fr: frNav, it: itNav };

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  return Object.entries(obj).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") {
      Object.assign(acc, flatten(value as Record<string, unknown>, path));
    } else {
      acc[path] = String(value);
    }
    return acc;
  }, {});
}

function translatorFor(locale: string) {
  const flat = flatten(CATALOGS[locale]);
  return (key: string) => flat[key] ?? key;
}

function sessionFor(role: SystemRoleKey): SessionInfo {
  return {
    authenticated: true,
    user: { id: "u1", first_name: "A", last_name: "B", display_name: "A B", email: "a@b.ch", preferred_language: "de", protocol_accordion_enabled: true, protocol_wheel_enabled: true },
    current_tenant: { id: "t1", name: "Tenant", profile_image_path: null, profile_image_url: null, enabled_features: ["finance", "abgabebox"] },
    permissions: [...SYSTEM_ROLE_PERMISSIONS[role]],
    roles: [{ id: `r-${role}`, name: null, system_key: role }],
  } as unknown as SessionInfo;
}

function adminSession(): SessionInfo {
  return sessionFor("admin");
}

describe("formatRoleLabel", () => {
  it.each(locales)("uebersetzt jede Standardrolle in '%s', ohne auf den Rollenschluessel zurueckzufallen", (locale) => {
    const t = translatorFor(locale);
    for (const role of ["admin", "writer", "kassier", "reader"] as const) {
      const label = formatRoleLabel(sessionFor(role), t);
      expect(label).not.toBe(role);
      expect(label.length).toBeGreaterThan(0);
    }
  });

  it("zeigt eigene Rollennamen und mehrere Rollen alphabetisch", () => {
    const t = translatorFor("de");
    const session = { roles: [{ id: "r1", name: "Revisor", system_key: null }, { id: "r2", name: null, system_key: "kassier" }] } as unknown as SessionInfo;
    expect(formatRoleLabel(session, t)).toBe(`${t("roles.kassier")}, Revisor`);
  });

  it("faellt ohne Rolle auf den Status-Text zurueck", () => {
    const t = translatorFor("de");
    expect(formatRoleLabel(null, t)).toBe(t("roles.status"));
    expect(formatRoleLabel({ roles: [] } as unknown as SessionInfo, t)).toBe(t("roles.status"));
  });
});

describe("buildNav", () => {
  const hrefsOf = (groups: ReturnType<typeof buildNav>, titleKey: string | null) =>
    groups.find((group) => group.titleKey === titleKey)?.links.map((link) => link.href) ?? [];

  it("ordnet nach Tätigkeiten: Bereiche oben, Einstellungen und Organisation unten", () => {
    const admin = buildNav(adminSession());
    expect(admin.map((group) => group.titleKey)).toEqual([
      null, "groups.sessions", "groups.tasks", "groups.members", "groups.cash", "groups.storage", "groups.appearance",
      SETTINGS_GROUP, "groups.organisation",
    ]);
    expect(hrefsOf(admin, null)).toEqual(["/", "/my-tasks"]);
    expect(hrefsOf(admin, "groups.sessions")).toEqual(["/events", "/agenda", "/protocols"]);
    expect(hrefsOf(admin, "groups.storage")).toEqual(["/lists", "/files", "/photos", "/shared-links"]);
    expect(hrefsOf(admin, "groups.organisation")).toEqual([
      "/tenant-settings", "/tenant-settings/abo", "/tenant-settings/privacy", "/tenant-settings/links", "/tenant-settings/activity", "/tools/import",
    ]);
  });

  it("zeigt «Fotos aus Abgaben» nur bei Freigabe und ohne «Fotos ansehen» (Phase 5)", () => {
    const reader = sessionFor("reader");
    expect(hrefsOf(buildNav(reader), "groups.storage")).not.toContain("/photos/submissions");
    const shared = { ...reader, shared_submission_photos: true } as SessionInfo;
    expect(hrefsOf(buildNav(shared), "groups.storage")).toContain("/photos/submissions");
    // Wer die Galerie sieht, braucht den zweiten Eintrag nicht
    expect(hrefsOf(buildNav({ ...adminSession(), shared_submission_photos: true } as SessionInfo), "groups.storage")).not.toContain("/photos/submissions");
  });

  it("sammelt die Einstellungen der Bereiche - jede nur mit dem Recht, sie zu öffnen", () => {
    expect(hrefsOf(buildNav(adminSession()), SETTINGS_GROUP)).toEqual([
      "/templates", "/task-packages", "/users", "/fine-settings", "/tenant-settings/domains",
    ]);
    // Aufgabenpakete und Arbeitsjahr brauchen templates.manage, Bussen-Regeln Feature finance
    expect(hrefsOf(buildNav(sessionFor("writer")), SETTINGS_GROUP)).toEqual(["/templates", "/fine-settings"]);
    expect(hrefsOf(buildNav(sessionFor("kassier")), SETTINGS_GROUP)).toEqual(["/fine-settings"]);
    const noFinance = { ...sessionFor("writer"), current_tenant: { ...sessionFor("writer").current_tenant!, enabled_features: ["abgabebox"] } } as SessionInfo;
    expect(hrefsOf(buildNav(noFinance), SETTINGS_GROUP)).not.toContain("/fine-settings");
    // Leser haben finances.read und sahen die Bussen-Einstellungen schon bisher - sonst nichts
    expect(hrefsOf(buildNav(sessionFor("reader")), SETTINGS_GROUP)).toEqual(["/fine-settings"]);
  });

  it("verweist von einem Bereich auf seine Einstellung und zurück", () => {
    const admin = buildNav(adminSession());
    expect(relatedNavLink(admin, "/fines")).toMatchObject({ kind: "settings", link: { href: "/fine-settings" } });
    expect(relatedNavLink(admin, "/protocols/abc")).toMatchObject({ kind: "settings", link: { href: "/templates" } });
    expect(relatedNavLink(admin, "/fine-settings")).toMatchObject({ kind: "area", groupTitleKey: "groups.cash", link: { href: "/finances" } });
    expect(relatedNavLink(admin, "/cycles")).toMatchObject({ kind: "area", groupTitleKey: "groups.sessions" });
    expect(relatedNavLink(admin, "/tenant-settings/verification")).toMatchObject({ kind: "area", groupTitleKey: "groups.appearance" });
    expect(relatedNavLink(admin, "/lists")).toBeNull();
    expect(relatedNavLink(admin, "/tenant-settings/abo")).toBeNull();
    // Ohne Recht auf die Einstellung kein Zahnrad
    expect(relatedNavLink(buildNav(sessionFor("reader")), "/todos")).toBeNull();
  });

  it("liefert fuer eine Admin-Session alle Gruppen mit uebersetzbaren labelKey/titleKey (keine fertigen Texte)", () => {
    const groups = buildNav(adminSession());
    expect(groups.length).toBeGreaterThan(1);
    for (const group of groups) {
      for (const link of group.links) {
        expect(typeof link.labelKey).toBe("string");
        // labelKey ist ein Uebersetzungs-Key (kurz, camelCase), kein fertiger Satz.
        expect(link.labelKey).toMatch(/^[a-zA-Z.]+$/);
      }
    }
  });

  it.each(locales)("jeder Navigationseintrag loest in '%s' zu einem nicht-leeren, uebersetzten Label auf", (locale) => {
    const t = translatorFor(locale);
    const groups = buildNav(adminSession());
    for (const group of groups) {
      if (group.titleKey) {
        expect(t(group.titleKey)).not.toBe(group.titleKey);
      }
      for (const link of group.links) {
        expect(t(link.labelKey)).not.toBe(link.labelKey);
      }
    }
  });

  it("isNavLinkActive erkennt die aktive Route unabhaengig von der Sprache (reine Pfadlogik)", () => {
    const groups = buildNav(adminSession());
    const dashboardLink = groups[0].links[0];
    expect(isNavLinkActive(dashboardLink, "/")).toBe(true);
    expect(isNavLinkActive(dashboardLink, "/statistics")).toBe(true);
    expect(isNavLinkActive(dashboardLink, "/participants")).toBe(false);
    const linkTo = (href: string) => groups.flatMap((group) => group.links).find((link) => link.href === href)!;
    // Unterseiten mit eigenem Eintrag markieren nur diesen
    expect(isNavLinkActive(linkTo("/tenant-settings"), "/tenant-settings")).toBe(true);
    expect(isNavLinkActive(linkTo("/tenant-settings"), "/tenant-settings/abo")).toBe(false);
    expect(isNavLinkActive(linkTo("/tenant-settings/privacy"), "/tenant-settings/retention")).toBe(true);
    expect(isNavLinkActive(linkTo("/documents"), "/documents/templates/1")).toBe(true);
    expect(isNavLinkActive(linkTo("/documents"), "/documents/brand")).toBe(false);
    expect(isNavLinkActive(linkTo("/documents/brand"), "/documents/assets")).toBe(true);
  });

  it("zeigt Bereiche nur mit der passenden Berechtigung", () => {
    const hrefs = (role: SystemRoleKey) => buildNav(sessionFor(role)).flatMap((group) => group.links.map((link) => link.href));
    expect(hrefs("reader")).not.toContain("/participants");
    expect(hrefs("reader")).not.toContain("/users");
    expect(hrefs("kassier")).toContain("/finances");
    expect(hrefs("kassier")).not.toContain("/templates");
    expect(hrefs("writer")).toContain("/participants");
    expect(hrefs("writer")).not.toContain("/tenant-settings");
    expect(hrefs("admin")).toEqual(expect.arrayContaining(["/users", "/tenant-settings", "/tools/import"]));
  });
});
