import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));

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

describe("AdminBackups", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockImplementation(async () => status());
  });

  it("unterscheidet erstellt, geprüft und Restore getestet", () => {
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    expect(screen.getByText("Backup erstellt")).toBeTruthy();
    expect(screen.getByText("Backup geprüft")).toBeTruthy();
    expect(screen.getByText("Noch kein erfolgreicher Restore-Test")).toBeTruthy();
    expect(screen.getByText("42 Sicherungspunkte, davon 1 geschützt")).toBeTruthy();
  });

  it("zeigt Probleme übersetzt und Aktionen nur für Owner", () => {
    const { rerender } = render(<AdminBackups initialStatus={status({ overall: "critical", problems: [{ code: "overdue", severity: "critical", params: { hours: 20 } }] })} initialSettings={settings} isOwner />);
    expect(screen.getByText("Das letzte erfolgreiche Backup ist 20 Stunden alt.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Backup jetzt starten" })).toBeTruthy();
    rerender(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner={false} />);
    expect(screen.queryByRole("button", { name: "Backup jetzt starten" })).toBeNull();
  });

  it("startet ein manuelles Backup als Auftrag", async () => {
    render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    fireEvent.click(screen.getByRole("button", { name: "Backup jetzt starten" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/backups", expect.objectContaining({ method: "POST" })));
  });

  it("zeigt den Fortschritt eines laufenden Backups", () => {
    render(<AdminBackups initialStatus={status({ current_job: {
      id: "j-1", kind: "backup", trigger: "manual", state: "running", requested_by_email: "owner@example.com", created_at: "2026-10-15T08:00:00Z",
      started_at: "2026-10-15T08:00:00Z", finished_at: null, heartbeat_at: "2026-10-15T08:01:00Z", worker_active: true, attempt: 0,
      cancel_requested: false, progress: { phase: "transfer", objects_total: 100, objects_done: 40, new_objects: 3, new_bytes: 4096 },
      error_code: null, error_message: null, warning_count: 0, duration_seconds: 60, backup_set: null,
    } })} initialSettings={settings} isOwner />);
    expect(screen.getByText("40 von 100 Objekten geprüft")).toBeTruthy();
    expect(screen.getByText("Schritt: Dateien werden übertragen")).toBeTruthy();
  });

  it("zeigt in den Einstellungen nie Secrets, nur ihren Status", () => {
    const { container } = render(<AdminBackups initialStatus={status()} initialSettings={settings} isOwner />);
    fireEvent.click(screen.getByRole("tab", { name: "Einstellungen" }));
    expect(screen.getByText("SSH-Schlüssel vorhanden · Passphrase vorhanden")).toBeTruthy();
    expect(container.textContent).not.toMatch(/PRIVATE KEY/);
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
