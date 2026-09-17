import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { FileStatCards } from "./file-stat-cards";

describe("FileStatCards", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the stat cards once loaded", async () => {
    browserApiFetchMock.mockResolvedValue({ document_count: 3, photo_count: 5, total_bytes: 1024 });

    render(<FileStatCards />);

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows a retry affordance instead of silently staying blank when the fetch fails (audit fix, 2026-09-17)", async () => {
    browserApiFetchMock.mockRejectedValueOnce(new Error("network error"));

    render(<FileStatCards />);

    const retryButton = await screen.findByRole("button", { name: "Erneut versuchen" });
    expect(screen.getByText(/nicht geladen werden/)).toBeInTheDocument();

    browserApiFetchMock.mockResolvedValueOnce({ document_count: 1, photo_count: 2, total_bytes: 512 });
    fireEvent.click(retryButton);

    await waitFor(() => expect(screen.queryByRole("button", { name: "Erneut versuchen" })).not.toBeInTheDocument());
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders nothing while the initial fetch is still pending", () => {
    browserApiFetchMock.mockReturnValue(new Promise(() => {}));

    const { container } = render(<FileStatCards />);

    expect(container).toBeEmptyDOMElement();
  });
});
