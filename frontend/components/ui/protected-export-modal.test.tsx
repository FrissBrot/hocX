import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const postAndDownload = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/download", () => ({ postAndDownload: (...args: unknown[]) => postAndDownload(...args) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { ProtectedExportForm } from "./protected-export-modal";

describe("ProtectedExportForm", () => {
  it("needs a long, repeated password and sends it only in the body", async () => {
    const onDone = vi.fn();
    const { container } = render(<ProtectedExportForm path="/api/users/me/personal-data" fallbackFilename="x.zip" onDone={onDone} />);
    const [first, second] = Array.from(container.querySelectorAll<HTMLInputElement>("input[type=password]"));
    const submit = screen.getByRole("button", { name: "Herunterladen" });
    const secret = crypto.randomUUID();

    fireEvent.change(first, { target: { value: "kurz" } });
    fireEvent.change(second, { target: { value: "kurz" } });
    expect(submit).toBeDisabled();

    fireEvent.change(first, { target: { value: secret } });
    fireEvent.change(second, { target: { value: `${secret}x` } });
    expect(submit).toBeDisabled();

    fireEvent.change(second, { target: { value: secret } });
    fireEvent.click(submit);

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(postAndDownload).toHaveBeenCalledWith("/api/users/me/personal-data", { password: secret }, "x.zip");
  });
});
