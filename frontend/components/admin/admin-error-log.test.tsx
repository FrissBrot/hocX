import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { AdminErrorLog } from "./admin-error-log";

const GROUPS = [{ error_type: "KeyError", count: 7, tenants: 2, first_at: "2026-11-10T10:00:00Z", last_at: "2026-11-20T10:00:00Z" }];

describe("AdminErrorLog", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.includes("/groups") ? GROUPS : { items: [], total: 0 }),
    );
  });

  it("zeigt die Gruppenansicht und springt per Klick zu den Einträgen des Typs", async () => {
    render(<AdminErrorLog initialPage={{ items: [], total: 0 }} initialFilterOptions={{ error_types: ["KeyError"], sources: ["backend"] }} tenants={[]} />);
    fireEvent.click(screen.getByRole("tab", { name: "Gruppiert" }));
    expect(await screen.findByText("7")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "KeyError" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenLastCalledWith(expect.stringContaining("error_type=KeyError")));
    expect(screen.getByRole("tab", { name: "Einträge" })).toHaveAttribute("aria-selected", "true");
  });
});
