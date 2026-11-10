import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));

import { AdminStorage, migrationStep } from "./admin-storage";
import { StorageGeneration, StorageMigration, StorageOverview, StorageProfile } from "@/types/api";

function profile(overrides: Partial<StorageProfile> = {}): StorageProfile {
  return {
    id: "p-1", name: "Hetzner Prod", provider: "hetzner", endpoint_url: "https://fsn1.your-objectstorage.com", region: "fsn1",
    bucket: "hocx-prod", abgabebox_bucket: null, prefix: "hocx", addressing_style: "virtual", access_key_masked: "••••1234",
    has_secret_key: true, has_restricted_credentials: false, tls_verify: true, has_ca_bundle: false, is_enabled: true, is_builtin: false,
    is_active: false, in_use_by_migration: false, pinned_generations: [], config_version: 1, last_test_at: "2026-10-14T10:00:00Z",
    last_test_ok: true, last_test_error: null, created_at: "2026-10-14T09:00:00Z", updated_at: "2026-10-14T09:00:00Z", ...overrides,
  };
}

function migration(overrides: Partial<StorageMigration> = {}): StorageMigration {
  return {
    id: "m-1", kind: "live", state: "awaiting_confirmation", resume_state: null, source_profile_name: "Lokales S3",
    source_provider: "garage_local", source_generation: 1, target_profile_name: "Hetzner Prod", target_provider: "hetzner",
    target_generation: 2, requested_by_email: "owner@example.com", options: {}, created_at: "2026-10-14T10:00:00Z", started_at: null,
    finished_at: null, phase_started_at: null, heartbeat_at: "2026-10-14T10:00:00Z", checkpoint_at: null, worker_active: false,
    total_objects: 0, total_bytes: 0, copied_objects: 0, copied_bytes: 0, verified_objects: 0, failed_objects: 0, status_counts: {},
    current_bps: null, average_bps: null, eta_seconds: null,
    estimate: {
      full: { remaining_low_seconds: 20 * 60, remaining_high_seconds: 35 * 60, safety_margin_seconds: 900 },
      cutover: { remaining_low_seconds: 60, remaining_high_seconds: 120, safety_margin_seconds: 60 },
    },
    live_estimate: null, last_error: null, attempt: 0, pause_requested: false, cancel_requested: false, cutover_confirmed_at: null,
    cutover_committed_at: null, needs_cutover_confirmation: false, reference_check: null, maintenance_window_id: null,
    final_integrity_ok: false, events: [], ...overrides,
  };
}

// Dateisystem-Profil aus der Zeit vor 1.2: nur noch deaktivierte Historie.
const legacyFilesystem = profile({
  id: "fs", name: "Lokales Dateisystem", provider: "filesystem", endpoint_url: null, region: null, bucket: null, prefix: "", is_builtin: true,
  is_enabled: false, access_key_masked: null, has_secret_key: false, last_test_at: null, last_test_ok: null,
});
const localS3 = profile({ id: "local", name: "Lokales S3", provider: "garage_local", endpoint_url: "http://garage:3900", bucket: "hocx", prefix: "", is_builtin: true, is_active: true, has_restricted_credentials: true });

function generation(overrides: Partial<StorageGeneration> = {}): StorageGeneration {
  return {
    id: 1, profile_id: "local", profile_name: "Lokales S3", generation: 1, status: "active", object_count: 12, total_bytes: 4096,
    created_at: "2026-10-14T09:00:00Z", activated_at: "2026-10-14T10:00:00Z", deactivated_at: null, retain_until: null,
    purge_requested_by: null, purged_at: null, purge_error: null, ...overrides,
  };
}

function overview(overrides: Partial<StorageOverview> = {}): StorageOverview {
  return {
    active_profile: localS3, active_generation: 1, write_fenced: false, fence_reason: null, credentials_key_configured: true,
    local_s3: { needed: true, reason: "active", configured: true, requested_until: null }, open_migration: null,
    generations: [generation()], profiles: [localS3, profile()], ...overrides,
  };
}

describe("AdminStorage", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockImplementation(async (path: string) => (path.startsWith("/api/admin/storage/migrations") ? [] : overview()));
  });

  it("zeigt Profile ohne Zugangsdaten und warnt bei geteilten Abgabebox-Zugangsdaten", () => {
    const { container } = render(<AdminStorage initialOverview={overview()} />);
    expect(screen.getByText("Hetzner Prod")).toBeTruthy();
    expect(screen.getByText("Abgabebox ohne eigene Zugangsdaten")).toBeTruthy();
    expect(container.textContent).not.toContain("1234");
  });

  it("zeigt vor dem Start die erwartete Kopierdauer und den Startknopf", () => {
    render(<AdminStorage initialOverview={overview({ open_migration: migration() })} />);
    expect(screen.getByText(/Erwartete Kopierdauer: 20–35 Minuten/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Migration starten" })).toBeTruthy();
    // Während eine Migration offen ist, kann keine zweite vorbereitet werden.
    expect((screen.getByRole("button", { name: "Migration vorbereiten" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("zeigt Fortschritt, Raten und warnt bei fehlendem Lebenszeichen des Workers", () => {
    render(<AdminStorage initialOverview={overview({ open_migration: migration({
      state: "copying", started_at: "2026-10-14T10:00:00Z", heartbeat_at: "2020-01-01T00:00:00Z", total_objects: 100, total_bytes: 1000,
      copied_objects: 40, copied_bytes: 400, verified_objects: 10, failed_objects: 2, average_bps: 2048, current_bps: 1024,
    }) })} />);
    expect(screen.getByText("10 von 100 Objekten geprüft")).toBeTruthy();
    expect(screen.getByText(/Storage-Worker meldet sich nicht mehr/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fehlgeschlagene erneut versuchen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pausieren" })).toBeTruthy();
  });

  it("bietet beim Umschalten keinen Abbruch mehr an", () => {
    render(<AdminStorage initialOverview={overview({ open_migration: migration({ state: "cutting_over" }) })} />);
    expect(screen.queryByRole("button", { name: "Abbrechen" })).toBeNull();
  });

  it("zeigt den aktiven S3-Speicher und Profile als Karten, ohne Erstmigration", () => {
    render(<AdminStorage initialOverview={overview()} />);
    expect(screen.getAllByText("Lokales S3").length).toBeGreaterThan(0);
    expect(screen.getByText("Keine Migration offen. Ein anderes Profil wird nur über eine Migration aktiv.")).toBeTruthy();
    expect(screen.getAllByText("•••••• verschlüsselt hinterlegt").length).toBeGreaterThan(0);
    expect(screen.getByText("Noch keine Migrationen.")).toBeTruthy();
    expect(screen.queryByText(/Erstmigration/)).toBeNull();
  });

  it("zeigt ein Dateisystem-Profil aus der Historie ohne Aktionen", async () => {
    const legacyOverview = overview({
      profiles: [localS3, legacyFilesystem],
      generations: [generation(), generation({ id: 0, profile_id: "fs", profile_name: "Lokales Dateisystem", generation: 0, status: "abandoned", activated_at: null })],
    });
    const initialMigration = migration({
      id: "m-0", kind: "initial", state: "completed", source_profile_name: "Lokales Dateisystem", source_provider: "filesystem",
      source_generation: 0, target_profile_name: "Lokales S3", target_provider: "garage_local", target_generation: 1, finished_at: "2026-10-14T11:00:00Z",
    });
    browserApiFetchMock.mockImplementation(async (path: string) => (path.startsWith("/api/admin/storage/migrations") ? [initialMigration] : legacyOverview));
    render(<AdminStorage initialOverview={legacyOverview} />);

    // Der Name steht auch in der Generationenliste - die Profilkarte ist das <article>.
    const card = screen.getAllByText("Lokales Dateisystem").map((element) => element.closest("article")).find(Boolean) as HTMLElement;
    expect(within(card).getByText("Dateisystem (bis 1.2, nicht mehr unterstützt)")).toBeTruthy();
    expect(within(card).getByText("Nicht mehr nutzbar – nur Verlauf")).toBeTruthy();
    expect(within(card).queryByRole("button")).toBeNull();
    // Die verworfene Dateisystem-Generation lässt sich nicht mehr bereinigen.
    expect(screen.queryByRole("button", { name: "Bereinigen" })).toBeNull();
    // Die Erstmigration erscheint nur noch als Eintrag im Verlauf.
    expect(await screen.findByText("Erstmigration (bis 1.2)")).toBeTruthy();
  });

  it("ordnet Migrationszustände den vier Schritten zu", () => {
    expect(migrationStep(null)).toBe(4);
    expect(migrationStep(migration({ state: "awaiting_confirmation" }))).toBe(0);
    expect(migrationStep(migration({ state: "copying" }))).toBe(1);
    expect(migrationStep(migration({ state: "verifying" }))).toBe(2);
    expect(migrationStep(migration({ state: "paused", resume_state: "verifying" }))).toBe(2);
    expect(migrationStep(migration({ state: "ready_for_cutover" }))).toBe(3);
    expect(migrationStep(migration({ state: "completed" }))).toBe(4);
  });
});
