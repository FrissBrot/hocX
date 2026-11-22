import { describe, expect, it } from "vitest";

import { buildNav, buildSettingsNav, formatRoleLabel, isNavLinkActive, isSettingsPath, relatedNavLink, SETTINGS_GROUP } from "./app-shell-nav";
import { locales } from "@/i18n/locale-config.generated";
import deNav from "@/messages/de/nav.json";
import enNav from "@/messages/en/nav.json";
import frNav from "@/messages/fr/nav.json";
import itNav from "@/messages/it/nav.json";
import deSettings from "@/messages/de/settings.json";
import enSettings from "@/messages/en/settings.json";
import frSettings from "@/messages/fr/settings.json";
import itSettings from "@/messages/it/settings.json";
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
  const hrefsOf = (groups: { titleKey: string | null; links: { href: string }[] }[], titleKey: string | null) =>
    groups.find((group) => group.titleKey === titleKey)?.links.map((link) => link.href) ?? [];
  const settingsOf = (session: SessionInfo) => buildSettingsNav(session);

  it("ordnet die Seitenleiste nach Tätigkeiten, ohne Einstellungen (Design «hocX Einstellungen»)", () => {
    const admin = buildNav(adminSession());
    expect(admin.map((group) => group.titleKey)).toEqual([null, "groups.sessions", "groups.tasks", "groups.cash", "groups.storage"]);
    expect(hrefsOf(admin, null)).toEqual(["/", "/my-tasks"]);
    expect(hrefsOf(admin, "groups.sessions")).toEqual(["/protocols", "/events", "/agenda"]);
    expect(hrefsOf(admin, "groups.tasks")).toEqual(["/todos", "/submission-assignments"]);
    expect(hrefsOf(admin, "groups.cash")).toEqual(["/finances", "/fines"]);
    expect(hrefsOf(admin, "groups.storage")).toEqual(["/participants", "/files", "/photos", "/lists"]);
    const settingsHrefs = settingsOf(adminSession()).flatMap((group) => group.links.map((link) => link.href));
    for (const href of settingsHrefs) {
      expect(admin.flatMap((group) => group.links.map((link) => link.href))).not.toContain(href);
    }
  });

  it("gruppiert die Einstellungen in Bereiche, Auftritt und Organisation", () => {
    const settings = settingsOf(adminSession());
    expect(settings.map((group) => group.titleKey)).toEqual(["groups.settingsAreas", "groups.appearance", "groups.organisation"]);
    expect(hrefsOf(settings, "groups.settingsAreas")).toEqual(["/templates", "/task-packages", "/fine-settings", "/users", "/tenant-settings/search"]);
    expect(hrefsOf(settings, "groups.appearance")).toEqual(["/documents", "/documents/brand", "/tenant-settings/domains"]);
    expect(hrefsOf(settings, "groups.organisation")).toEqual([
      "/tenant-settings", "/tenant-settings/abo", "/tenant-settings/privacy", "/tenant-settings/links", "/shared-links", "/tenant-settings/activity",
      "/tenant-settings/security", "/tools/import",
    ]);
  });

  it("zeigt «Sicherheit & Anmeldungen» nur mit security.read", () => {
    expect(hrefsOf(settingsOf(adminSession()), "groups.organisation")).toContain("/tenant-settings/security");
    for (const role of ["writer", "kassier", "reader"] as const) {
      expect(settingsOf(sessionFor(role)).flatMap((group) => group.links.map((link) => link.href))).not.toContain("/tenant-settings/security");
    }
  });

  it("zeigt «Fotos aus Abgaben» nur bei Freigabe und ohne «Fotos ansehen» (Phase 5)", () => {
    const reader = sessionFor("reader");
    expect(hrefsOf(buildNav(reader), "groups.storage")).not.toContain("/photos/submissions");
    const shared = { ...reader, shared_submission_photos: true } as SessionInfo;
    expect(hrefsOf(buildNav(shared), "groups.storage")).toContain("/photos/submissions");
    // Wer die Galerie sieht, braucht den zweiten Eintrag nicht
    expect(hrefsOf(buildNav({ ...adminSession(), shared_submission_photos: true } as SessionInfo), "groups.storage")).not.toContain("/photos/submissions");
  });

  it("zeigt jede Einstellung nur mit dem Recht, sie zu öffnen", () => {
    const allHrefs = (session: SessionInfo) => settingsOf(session).flatMap((group) => group.links.map((link) => link.href));
    // Aufgabenpakete und Arbeitsjahr brauchen templates.manage, Bussen-Regeln Feature finance
    expect(hrefsOf(settingsOf(sessionFor("writer")), "groups.settingsAreas")).toEqual(["/templates", "/fine-settings"]);
    expect(hrefsOf(settingsOf(sessionFor("kassier")), "groups.settingsAreas")).toEqual(["/fine-settings"]);
    const noFinance = { ...sessionFor("writer"), current_tenant: { ...sessionFor("writer").current_tenant!, enabled_features: ["abgabebox"] } } as SessionInfo;
    expect(allHrefs(noFinance)).not.toContain("/fine-settings");
    // Leser haben finances.read und sahen die Bussen-Einstellungen schon bisher - sonst nichts
    expect(hrefsOf(settingsOf(sessionFor("reader")), "groups.settingsAreas")).toEqual(["/fine-settings"]);
    expect(allHrefs(sessionFor("reader"))).not.toContain("/tenant-settings");
    expect(allHrefs(sessionFor("writer"))).not.toContain("/tenant-settings");
    // Ohne jede Einstellung: kein Knopf, keine Übersicht
    expect(buildSettingsNav({ permissions: [], current_tenant: null })).toEqual([]);
  });

  it("markiert Übersicht und alle Einstellungsseiten als «in den Einstellungen»", () => {
    const settings = settingsOf(adminSession());
    expect(isSettingsPath(settings, "/settings")).toBe(true);
    expect(isSettingsPath(settings, "/tenant-settings/retention")).toBe(true);
    expect(isSettingsPath(settings, "/cycles")).toBe(true);
    expect(isSettingsPath(settings, "/documents/assets")).toBe(true);
    expect(isSettingsPath(settings, "/fines")).toBe(false);
    expect(isSettingsPath(settings, "/")).toBe(false);
  });

  it("verweist von einem Bereich auf seine Einstellung und zurück", () => {
    const admin = buildNav(adminSession());
    const settings = settingsOf(adminSession());
    expect(relatedNavLink(admin, settings, "/fines")).toMatchObject({ kind: "settings", link: { href: "/fine-settings" } });
    expect(relatedNavLink(admin, settings, "/protocols/abc")).toMatchObject({ kind: "settings", link: { href: "/templates" } });
    expect(relatedNavLink(admin, settings, "/participants")).toMatchObject({ kind: "settings", link: { href: "/users" } });
    expect(relatedNavLink(admin, settings, "/fine-settings")).toMatchObject({ kind: "area", groupTitleKey: "groups.cash", link: { href: "/finances" } });
    expect(relatedNavLink(admin, settings, "/cycles")).toMatchObject({ kind: "area", groupTitleKey: "groups.sessions" });
    expect(relatedNavLink(admin, settings, "/users/roles")).toMatchObject({ kind: "area", groupTitleKey: "participants", link: { href: "/participants" } });
    expect(relatedNavLink(admin, settings, "/lists")).toBeNull();
    expect(relatedNavLink(admin, settings, "/tenant-settings/abo")).toBeNull();
    // Ohne Recht auf die Einstellung kein Zahnrad
    const reader = sessionFor("reader");
    expect(relatedNavLink(buildNav(reader), settingsOf(reader), "/todos")).toBeNull();
  });

  it("liefert fuer eine Admin-Session alle Gruppen mit uebersetzbaren labelKey/titleKey (keine fertigen Texte)", () => {
    const groups = [...buildNav(adminSession()), ...settingsOf(adminSession())];
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
    const groups = [...buildNav(adminSession()), ...settingsOf(adminSession())];
    expect(t(SETTINGS_GROUP)).not.toBe(SETTINGS_GROUP);
    for (const group of groups) {
      if (group.titleKey) {
        expect(t(group.titleKey)).not.toBe(group.titleKey);
      }
      for (const link of group.links) {
        expect(t(link.labelKey)).not.toBe(link.labelKey);
        if ("area" in link && link.area) {
          expect(t(link.area.titleKey)).not.toBe(link.area.titleKey);
        }
      }
    }
  });

  it("isNavLinkActive erkennt die aktive Route unabhaengig von der Sprache (reine Pfadlogik)", () => {
    const groups = [...buildNav(adminSession()), ...settingsOf(adminSession())];
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
    const hrefs = (role: SystemRoleKey) =>
      [...buildNav(sessionFor(role)), ...settingsOf(sessionFor(role))].flatMap((group) => group.links.map((link) => link.href));
    expect(hrefs("reader")).not.toContain("/participants");
    expect(hrefs("reader")).not.toContain("/users");
    expect(hrefs("kassier")).toContain("/finances");
    expect(hrefs("kassier")).not.toContain("/templates");
    expect(hrefs("writer")).toContain("/participants");
    expect(hrefs("writer")).not.toContain("/tenant-settings");
    expect(hrefs("admin")).toEqual(expect.arrayContaining(["/users", "/tenant-settings", "/tools/import"]));
  });
});

describe("settings hub cards", () => {
  // Die Übersicht (settings-overview.tsx) zeigt je Link «hub.cards.<labelKey>.description» - fehlt der
  // Text, erscheint der rohe Schlüssel (Abnahme r93: «Suche & Synonyme»).
  const SETTINGS_CATALOGS: Record<string, Record<string, unknown>> = { de: deSettings, en: enSettings, fr: frSettings, it: itSettings };
  it("has a card description for every settings link in every locale", () => {
    const labelKeys = new Set<string>();
    for (const role of Object.keys(SYSTEM_ROLE_PERMISSIONS) as SystemRoleKey[]) {
      for (const group of buildSettingsNav(sessionFor(role))) {
        for (const link of group.links) labelKeys.add(link.labelKey);
      }
    }
    expect(labelKeys.size).toBeGreaterThan(0);
    const missing: string[] = [];
    for (const locale of locales) {
      const flat = flatten(SETTINGS_CATALOGS[locale]);
      for (const key of labelKeys) {
        if (!flat[`hub.cards.${key}.description`]) missing.push(`${locale}:${key}`);
      }
    }
    expect(missing).toEqual([]);
  });
});
