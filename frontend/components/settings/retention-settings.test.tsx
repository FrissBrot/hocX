import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch, toast, confirm } = vi.hoisted(() => ({ apiFetch: vi.fn(), toast: vi.fn(), confirm: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

import { RetentionSettings } from "./retention-settings";

const policy = { submissions_months: 12, unlinked_gallery_years: null, auto_apply: false };

describe("RetentionSettings › Fristen", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    toast.mockReset();
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => (init?.method === "PUT" ? JSON.parse(String(init.body)) : []));
  });

  it("lässt das Zahlenfeld leeren, ohne sofort 1 einzusetzen (sonst wird aus «24» beim Tippen «124»)", async () => {
    render(<RetentionSettings initialPolicy={policy} />);
    const months = screen.getByLabelText("Monate") as HTMLInputElement;
    const save = screen.getByRole("button", { name: "Speichern" });

    fireEvent.change(months, { target: { value: "" } });
    expect(months.value).toBe("");
    expect(save).toBeDisabled();

    fireEvent.change(months, { target: { value: "24" } });
    expect(months.value).toBe("24");
    fireEvent.click(save);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/api/retention/policy", expect.objectContaining({ method: "PUT", body: JSON.stringify({ ...policy, submissions_months: 24 }) }))
    );
  });

  it("speichert keine Frist ausserhalb des erlaubten Bereichs", () => {
    render(<RetentionSettings initialPolicy={policy} />);
    const months = screen.getByLabelText("Monate") as HTMLInputElement;
    fireEvent.change(months, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
    fireEvent.change(months, { target: { value: "241" } });
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
  });
});
