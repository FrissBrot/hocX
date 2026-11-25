import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));
const replaceMock = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => "/admin/backups",
  useSearchParams: () => searchParams,
}));
const stepUpFetchMock = vi.fn();
vi.mock("@/lib/admin-step-up", () => ({ stepUpFetch: (...args: unknown[]) => stepUpFetchMock(...args) }));

import { AdminBackups, useIdempotencyKey } from "./admin-backups";
import { BackupSet, BackupSettings, BackupStatus } from "@/types/api";

function backupSet(overrides: Partial<BackupSet> = {}): BackupSet {
  return {
    id: "s-1", archive_name: "hocx-rp-20261015T061500Z-0123456789abcdef0123456789abcdef", state: "completed", trigger: "schedule",
    protected: false, protected_reason: null, snapshot_at: "2026-10-15T06:15:00Z", finished_at: "2026-10-15T06:20:00Z", app_version: "1.2.0",
    alembic_revision: "0115_backup_system", generation: 3, profile_name: "Hetzner Prod", profile_provider: "hetzner", db_dump_bytes: 1048576,
    object_count: 1200, object_bytes: 5 * 1024 ** 3, new_object_count: 12, new_object_bytes: 2048, deduplicated_bytes: 1500,
    duration_seconds: 300, verify_state: "verified", verified_at: "2026-10-15T07:00:00Z", restore_test_state: "untested",
    restore_tested_at: null, warnings: [], tenant_count: 2, reconstructed: false, ...overrides,
  };
}

const repository = {
  ok: true, checked_at: "2026-10-15T07:00:00Z", last_ok_at: "2026-10-15T07:00:00Z", error_code: null, error: null,
  repository_id: "a".repeat(64), encryption: "repokey-blake2", borg_version: "borg 1.4.0", stored_bytes: 3 * 1024 ** 3,
  original_bytes: 80 * 1024 ** 3, deduplicated_bytes: 4 * 1024 ** 3, quota_bytes: 1024 ** 4, used_percent: 0.3, staging_free_bytes: 50 * 1024 ** 3,
  staging_total_bytes: 100 * 1024 ** 3, last_gc_at: null, last_verify_at: null, last_verify_ok: null, last_restore_test_at: null,
  last_restore_test_ok: null,
};

function status(overrides: Partial<BackupStatus> = {}): BackupStatus {
  return {
    enabled: true, overall: "ok", problems: [], last_success: backupSet(), last_failure: null, next_backup_at: "2026-10-15T12:15:00Z",
    restore_point_count: 42, protected_count: 1, latest_object_bytes: 5 * 1024 ** 3, latest_db_bytes: 1048576, repository,
    last_verified_at: "2026-10-15T07:00:00Z", last_verified_archive: "hocx-rp-x", last_restore_test_at: null, last_restore_test_archive: null,
    current_job: null, current_restore: null, worker_heartbeat_at: "2026-10-15T07:59:00Z", worker_alive: true, ...overrides,
  };
}

const settings: BackupSettings = {
  schedule_enabled: true, interval_hours: 6, schedule_offset_minutes: 15, keep_within_days: 14, keep_daily: 14, keep_weekly: 8, keep_monthly: 12,
  verify_interval_hours: 168, verify_sample_objects: 200, restore_test_interval_days: 30, success_notification: "daily",
  worker_config: { repository: "ssh://u1@u1.your-storagebox.de:23/./hocx", host_key_pinned: true, repository_id_pinned: true,
    ssh_key_configured: true, passphrase_configured: true, staging_max_bytes: 20 * 1024 ** 3 },
  repository, ntfy_configured: true, updated_at: "2026-10-15T07:00:00Z", updated_by_email: null,
};

function apiMock(overrides: Record<string, unknown> = {}) {
  return async (path: string) => {
    for (const [prefix, value] of Object.entries(overrides)) if (path.startsWith(prefix)) return value;
    if (path.startsWith("/api/admin/backups/status")) return status();
    if (path.startsWith("/api/admin/backups/sets")) return [];
    if (path.startsWith("/api/admin/restores")) return [];
    if (path.startsWith("/api/admin/storage/overview")) return { profiles: [] };
    if (path.startsWith("/api/admin/backups")) return { items: [], total: 0, offset: 0, limit: 25, counts: {} };
    return null;
  };
}

describe("AdminBackups", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockImplementation(apiMock());
    replaceMock.mockReset();
    stepUpFetchMock.mockReset();
    searchParams = new URLSearchParams();
  });

  it("zeigt Gesamtstatus und die drei Nachweise", () => {
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    expect(screen.getByText("Alle Daten sind offsite gesichert.")).toBeTruthy();
    expect(screen.getByText("Drei Nachweise")).toBeTruthy();
    expect(screen.getByText("Backup erstellt")).toBeTruthy();
    expect(screen.getByText("Integrität geprüft")).toBeTruthy();
    expect(screen.getByText("Restore getestet")).toBeTruthy();
    expect(screen.getByText("Speicher")).toBeTruthy();
  });

  it("zeigt Probleme übersetzt mit Aktion und Aktionen nur für Owner", () => {
    const critical = status({ overall: "critical", problems: [{ code: "overdue", severity: "critical", params: { hours: 20 } }] });
    const { rerender } = render(<AdminBackups initialStatus={critical} initialSettings={settings} isOwner />);
    expect(screen.getByText("Das letzte erfolgreiche Backup ist 20 Stunden alt.")).toBeTruthy();
    expect(screen.getByText("Das letzte erfolgreiche Backup ist zu alt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Verlauf öffnen" }));
    expect(replaceMock).toHaveBeenCalledWith(expect.stringContaining("tab=history"), { scroll: false });
    expect(replaceMock.mock.calls[0][0]).toContain("state=failed");
    expect(screen.getByRole("button", { name: "Backup jetzt starten" })).toBeTruthy();
    rerender(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner={false} />);
    expect(screen.queryByRole("button", { name: "Backup jetzt starten" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Jetzt prüfen" })).toBeNull();
    expect(screen.getByText(/Du siehst den Zustand, kannst aber nichts verändern/)).toBeTruthy();
  });

  it("startet ein manuelles Backup als Auftrag", async () => {
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    fireEvent.click(screen.getByRole("button", { name: "Backup jetzt starten" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/backups", expect.objectContaining({ method: "POST" })));
  });

  it("prüft den letzten Punkt über seinen Backup-Auftrag", async () => {
    render(<AdminBackups initialStatus={status({ last_success: backupSet({ job_id: "11111111-1111-4111-8111-111111111111" }) })} initialSettings={settings} isOwner />);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt prüfen" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/backups/11111111-1111-4111-8111-111111111111/verify", expect.objectContaining({ method: "POST" })));
  });

  it("zeigt den Fortschritt eines laufenden Backups", () => {
    render(<AdminBackups initialStatus={status({ current_job: {
      id: "j-1", kind: "backup", trigger: "manual", state: "running", requested_by_email: "owner@example.com", created_at: "2026-10-15T08:00:00Z",
      started_at: "2026-10-15T08:00:00Z", finished_at: null, heartbeat_at: "2026-10-15T08:01:00Z", worker_active: true, attempt: 0,
      cancel_requested: false, progress: { phase: "transfer", objects_total: 100, objects_done: 40, new_objects: 3, new_bytes: 4096 },
      error_code: null, error_message: null, warning_count: 0, duration_seconds: 60, backup_set: null,
    } })} initialSettings={settings} isOwner />);
    expect(screen.getByText("Ein Backup läuft gerade.")).toBeTruthy();
    expect(screen.getByText("40 von 100 Objekten geprüft")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Schritte des Auftrags" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Backup jetzt starten" })).toHaveProperty("disabled", true);
  });

  it("behält «nicht eingerichtet» und «Worker läuft nicht»", () => {
    const { unmount } = render(<AdminBackups initialStatus={status({ enabled: false, overall: "disabled" })} initialSettings={settings} isOwner />);
    expect(screen.getByText(/noch nicht eingerichtet/)).toBeTruthy();
    unmount();
    render(<AdminBackups initialStatus={status({ worker_alive: false })} initialSettings={settings} isOwner />);
    expect(screen.getByText(/Der Backup-Worker meldet sich nicht/)).toBeTruthy();
  });

  it("schreibt den Reiter in die URL und liest ihn daraus", () => {
    const { unmount } = render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    fireEvent.click(screen.getByRole("tab", { name: "Verlauf" }));
    expect(replaceMock).toHaveBeenCalledWith("/admin/backups?tab=history", { scroll: false });
    unmount();
    searchParams = new URLSearchParams("tab=settings");
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    expect(screen.getByRole("tab", { name: "Einstellungen" }).getAttribute("aria-selected")).toBe("true");
  });

  it("zeigt in den Einstellungen nie Secrets, nur ihren Status", () => {
    searchParams = new URLSearchParams("tab=settings");
    const { container } = render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    expect(screen.getByText("SSH-Schlüssel vorhanden · Passphrase vorhanden")).toBeTruthy();
    expect(screen.getByText("ssh://u1@u1.your-storagebox.de:23/./hocx")).toBeTruthy();
    expect(container.textContent).not.toMatch(/PRIVATE KEY/);
  });

  it("speichert Einstellungen nur mit Passkey und nur bei Änderung", async () => {
    searchParams = new URLSearchParams("tab=settings");
    stepUpFetchMock.mockResolvedValue(settings);
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    const save = screen.getByRole("button", { name: "Mit Passkey speichern" });
    expect(save).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("radio", { name: /Jedes Backup/ }));
    expect(save).toHaveProperty("disabled", false);
    fireEvent.click(save);
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalledWith("backup-settings", "/api/admin/backups/settings", expect.objectContaining({ method: "PUT" })));
  });

  it("Support sieht keine Verbindungsadresse, wenn die API sie nicht liefert", () => {
    searchParams = new URLSearchParams("tab=settings");
    const support = { ...settings, worker_config: { host_key_pinned: true, repository_id_pinned: true } };
    render(<AdminBackups initialStatus={status()} initialSettings={support} isOwner={false} />);
    expect(screen.queryByText(/storagebox/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Mit Passkey speichern" })).toBeNull();
  });

  it("Wiederherstellung: Phrase an den Punkt gebunden, Enter startet nichts", async () => {
    searchParams = new URLSearchParams("tab=restore");
    const set = backupSet({ id: "a1b2c3d4-0000-4000-8000-000000000000" });
    browserApiFetchMock.mockImplementation(apiMock({
      "/api/admin/backups/sets/": [{ id: 5, public_id: null, name: "Pfadi", users: 4, objects: 10, bytes: 1000 }],
      "/api/admin/backups/sets": [set],
      "/api/admin/restores/preview": {
        kind: "tenant_copy", backup_set: set, schema_state: "same", schema_revision: "0280", schema_head: "0280", target_profile_name: null,
        target_profile_provider: null, tenant: { id: 5, public_id: null, name: "Pfadi", users: 4, objects: 10, bytes: 1000 }, new_name: "Pfadi (Wiederherstellung)",
        name_conflict: false, steps: ["collect_tenant"], risks: ["not_verified"], blockers: [], confirmation_phrase: "KOPIE a1b2c3d4", requires_passkey: true, estimated_bytes: 1000,
      },
    }));
    stepUpFetchMock.mockResolvedValue({ id: "r-1" });
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    fireEvent.click(await screen.findByRole("radio", { name: /hocx-rp-20261015/ }));
    fireEvent.click(await screen.findByRole("radio", { name: /Pfadi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Vorschau erstellen" }));
    const input = await screen.findByPlaceholderText("KOPIE a1b2c3d4");
    expect((input as HTMLInputElement).value).toBe("");
    const submit = screen.getByRole("button", { name: "Mandant als Kopie wiederherstellen" });
    expect(submit).toHaveProperty("disabled", true);
    expect(screen.getByText(/Kurz-ID des gewählten Sicherungspunkts/)).toBeTruthy();
    fireEvent.change(input, { target: { value: "KOPIE a1b2c3d4" } });
    expect(submit).toHaveProperty("disabled", false);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(stepUpFetchMock).not.toHaveBeenCalled();
    fireEvent.click(submit);
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalledWith("backup-restore", "/api/admin/restores", expect.objectContaining({ method: "POST" })));
    expect(JSON.parse(stepUpFetchMock.mock.calls[0][2].body)).toMatchObject({ confirmation: "KOPIE a1b2c3d4", source_tenant_id: 5, replay_erasures: true });
  });
});

describe("useIdempotencyKey", () => {
  it("liefert bis zum Zurücksetzen denselben Schlüssel (Wiederholung nach Netzwerkfehler)", () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey());
    const first = result.current.get("restore-s-1");
    rerender();
    expect(result.current.get("restore-s-1")).toBe(first);
    expect(first).toMatch(/^restore-s-1-[A-Za-z0-9_.:-]+$/);
    act(() => result.current.reset());
    expect(result.current.get("restore-s-1")).not.toBe(first);
  });
});
