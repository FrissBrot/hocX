import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { AdminJobStatus } from "./admin-job-status";
import { JobStatusEntry } from "@/types/api";

function makeJob(overrides: Partial<JobStatusEntry> = {}): JobStatusEntry {
  return {
    name: "upload_pipeline_rescan",
    registered: true,
    kind: "loop",
    service: "backend",
    category: "virus_scan",
    interval_seconds: 900,
    max_silence_seconds: 2700,
    state: "ok",
    last_status: "success",
    last_started_at: "2026-10-11T10:00:00Z",
    last_finished_at: "2026-10-11T10:00:02Z",
    last_success_at: "2026-10-11T10:00:02Z",
    last_failure_at: null,
    last_heartbeat_at: null,
    last_duration_ms: 2000,
    last_error: null,
    consecutive_failures: 0,
    run_count: 10,
    failure_count: 0,
    ...overrides,
  };
}

describe("AdminJobStatus", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
  });

  it("gruppiert Jobs nach Kategorie und zeigt den Zustand", () => {
    render(
      <AdminJobStatus
        initialOverview={{
          generated_at: "2026-10-11T10:01:00Z",
          items: [
            makeJob(),
            makeJob({ name: "photo_analysis_worker", kind: "worker", service: "photo-analysis-worker", category: "photo_analysis", interval_seconds: null, state: "overdue" }),
            makeJob({ name: "backup_db", registered: false, kind: null, service: null, category: null, interval_seconds: null, max_silence_seconds: null }),
          ],
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Virenprüfung" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Bildanalyse" })).toBeInTheDocument();
    expect(screen.getByText("Nachprüfung interner Uploads")).toBeInTheDocument();
    expect(screen.getByText("alle 15 Minuten")).toBeInTheDocument();
    expect(screen.getByText("Überfällig")).toBeInTheDocument();
    // Nicht registrierte Jobs erscheinen unter ihrem Rohnamen im Abschnitt "Weitere".
    expect(screen.getByRole("heading", { name: "Weitere" })).toBeInTheDocument();
    expect(screen.getByText("backup_db")).toBeInTheDocument();
    expect(screen.getByText("Nicht registriert")).toBeInTheDocument();
  });

  it("öffnet beim Klick die Details mit letzter Fehlermeldung und Verlauf", async () => {
    browserApiFetchMock.mockResolvedValue({
      items: [{ id: 1, status: "failure", started_at: "2026-10-11T10:00:00Z", finished_at: "2026-10-11T10:00:01Z", duration_ms: 1000, error: "OSError: disk full" }],
      total: 1,
    });
    render(
      <AdminJobStatus
        initialOverview={{
          generated_at: "2026-10-11T10:01:00Z",
          items: [makeJob({ name: "export_cleanup", category: "cleanup", state: "failing", consecutive_failures: 3, last_error: "OSError: disk full" })],
        }}
      />,
    );

    expect(screen.getByText("3 Fehlschläge in Folge")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Exporte aufräumen"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("OSError: disk full")).toBeInTheDocument();
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/jobs/export_cleanup/runs?limit=20&offset=0"));
    // Zeile im Verlauf (zusätzlich zum Status-Badge oben im Dialog).
    await waitFor(() => expect(within(dialog).getAllByText("Fehlgeschlagen", { selector: ".badge" })).toHaveLength(2));
  });
});
