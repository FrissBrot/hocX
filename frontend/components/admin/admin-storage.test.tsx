import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));

import { AdminStorage } from "./admin-storage";
import { StorageMigration, StorageOverview, StorageProfile } from "@/types/api";

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
    id: "m-1", kind: "initial", state: "awaiting_confirmation", resume_state: null, source_profile_name: "Dateisystem",
    source_provider: "filesystem", source_generation: 0, target_profile_name: "Lokales S3", target_provider: "garage_local",
    target_generation: 1, requested_by_email: "owner@example.com", options: {}, created_at: "2026-10-14T10:00:00Z", started_at: null,
    finished_at: null, phase_started_at: null, heartbeat_at: "2026-10-14T10:00:00Z", checkpoint_at: null, worker_active: false,
    total_objects: 0, total_bytes: 0, copied_objects: 0, copied_bytes: 0, verified_objects: 0, failed_objects: 0, status_counts: {},
    current_bps: null, average_bps: null, eta_seconds: null,
    estimate: { full: { remaining_low_seconds: 20 * 60, remaining_high_seconds: 35 * 60, safety_margin_seconds: 900 } },
    live_estimate: null, last_error: null, attempt: 0, pause_requested: false, cancel_requested: false, cutover_confirmed_at: null,
    cutover_committed_at: null, needs_cutover_confirmation: false, reference_check: null, maintenance_window_id: null,
    final_integrity_ok: false, events: [], ...overrides,
  };
}

function overview(overrides: Partial<StorageOverview> = {}): StorageOverview {
  const filesystem = profile({ id: "fs", name: "Dateisystem", provider: "filesystem", endpoint_url: null, bucket: null, prefix: "", is_builtin: true, is_active: true, access_key_masked: null, has_secret_key: false });
  return {
    active_profile: filesystem, active_generation: 0, write_fenced: false, fence_reason: null, credentials_key_configured: true,
    local_s3: { needed: true, reason: "initial_target", configured: true, requested_until: null }, open_migration: null,
    generations: [], profiles: [filesystem, profile()], ...overrides,
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

  it("zeigt vor dem Start die erwartete Wartungsdauer und den Startknopf", () => {
    render(<AdminStorage initialOverview={overview({ open_migration: migration() })} />);
    expect(screen.getByText(/Erwartete Wartungsdauer: 20–35 Minuten/)).toBeTruthy();
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
});
