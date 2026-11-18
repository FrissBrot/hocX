import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { AdminEmailLog } from "./admin-email-log";
import type { NotificationLogPage } from "@/types/api";

const PAGE: NotificationLogPage = {
  total: 2,
  items: [
    {
      id: "n1", created_at: "2026-11-17T20:00:00Z", deliver_after: "2026-11-17T20:00:00Z", sent_at: "2026-11-17T20:01:00Z",
      tenant_name: "Alpha Team", recipient_name: "Anna Muster", recipient_email: "anna@example.com", kind: "todo.due_soon",
      status: "sent", skip_reason: null, attempts: 2, last_error: null,
    },
    {
      id: "n2", created_at: "2026-11-17T20:00:00Z", deliver_after: "2026-11-17T20:00:00Z", sent_at: null,
      tenant_name: "Beta Gruppe", recipient_name: "Ben Muster", recipient_email: "ben@example.com", kind: "todo.overdue",
      status: "skipped", skip_reason: "obsolete", attempts: 0, last_error: null,
    },
  ],
};

describe("AdminEmailLog", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue(PAGE);
  });

  it("zeigt Empfänger, Art und Ergebnis und filtert nach Status", async () => {
    render(<AdminEmailLog />);
    expect(await screen.findByText("Anna Muster")).toBeInTheDocument();
    expect(screen.getByText("anna@example.com")).toBeInTheDocument();
    expect(screen.getByText("Erinnerung: bald fällig")).toBeInTheDocument();
    expect(screen.getByText("2 Versuche")).toBeInTheDocument();
    expect(screen.getByText(/überholt/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Übersprungen" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenLastCalledWith(expect.stringContaining("status=skipped")));
  });
});
