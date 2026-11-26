import { defineConfig, devices } from "@playwright/test";

// Specs, die Datei-Importe des Demo-Mandanten anlegen und abbrechen (Projekt «tenant-import»).
const IMPORT_SPECS = /(file-import|cloud-import-[a-z]+)\.spec\.ts/;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 45_000,
  // Lokal laufen Stack (Dev-Server mit Kompilierung, ClamAV, Worker) und Browser auf demselben Host:
  // mit 4 Workern auf 8 Kernen stand der Renderer zeitweise >30 s still (Tastendruck kam nie an,
  // Antworten über 15 s) - Fehler nur aus Zeitmangel. scripts/e2e.sh setzt E2E_WORKERS (Standard 2,
  // wie ein GitHub-Runner mit 4 Kernen ohnehin bekommt); ohne Variable entscheidet Playwright.
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : undefined,
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
    { name: "chromium", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["setup"], testIgnore: [/auth\.setup\.ts/, /feature-gating\.spec\.ts/, /storage-quota\.spec\.ts/, /storage-packages\.spec\.ts/, IMPORT_SPECS] },
    // Datei-Import (ZIP/Ordner und Cloud-Quellen): ein Import je Mandant gleichzeitig, und jede Spec bricht
    // zu Beginn offene Importe ab. Parallel brach file-import.spec den Microsoft-Import der anderen
    // Worker-Instanz ab - deshalb ein Worker für alle Import-Specs (parallel zu «chromium»).
    { name: "tenant-import", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["setup"], testMatch: IMPORT_SPECS, workers: 1 },
    // feature-gating.spec.ts schaltet alle Module des gemeinsamen Demo-Mandanten kurz ab. Parallel
    // zu anderen Specs liefen deren Abgabebox-/Finanz-Aufrufe dann zufaellig in 403 (z.B.
    // captcha-verify in abgabebox-photo-album-sync.spec.ts) - deshalb erst nach allen anderen.
    { name: "tenant-wide", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["chromium", "tenant-import"], testMatch: /feature-gating\.spec\.ts/ },
    // storage-quota.spec.ts setzt den Demo-Mandanten auf einen knappen Plan, storage-packages.spec.ts
    // weist ihm Zusatzspeicher zu - beide ändern dasselbe Kontingent. Parallel zueinander (oder zu
    // Upload-Specs) sah jede die Änderung der anderen (400 erwartet, 201 erhalten bzw. falsches
    // Kontingent). Deshalb nacheinander und erst nach allen anderen.
    { name: "tenant-quota", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["tenant-wide"], testMatch: /storage-quota\.spec\.ts/ },
    { name: "tenant-packages", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/admin.json" }, dependencies: ["tenant-quota"], testMatch: /storage-packages\.spec\.ts/ },
  ],
  outputDir: "test-results/playwright",
});
