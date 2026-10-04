import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 45_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    permissions: ["clipboard-read", "clipboard-write"],
    // Der ganze Suite-Text ist auf Deutsch verdrahtet (siehe z.B. abgabe-links.spec.ts:
    // "Nicht gefunden"). Vor next-intl gab es keine andere Sprache; seit next-intl faellt eine
    // Seite ohne gespeicherte Praeferenz/Cookie auf die Browser-Sprache zurueck (CLAUDE.md,
    // i18n-Abschnitt, Stufe 3) - Playwrights Default-Locale ist Englisch, was unauthentifizierte
    // Kontexte (kein gespeicherter preferred_language-Cookie) plötzlich auf Englisch rendern
    // liess. browser.newContext() ohne eigenes `locale` erbt dieses Projekt-Default (siehe
    // navigation.spec.ts zum selben Mechanismus bei storageState), fixt also auch die Faelle in
    // abgabe-links.spec.ts/abgabebox-photo-album-sync.spec.ts, die ihren eigenen Kontext fuer die
    // oeffentliche Abgabebox-Seite aufmachen.
    locale: "de-CH",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "chromium", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["setup"], testIgnore: /auth\.setup\.ts/ },
  ],
  outputDir: "test-results/playwright",
});
