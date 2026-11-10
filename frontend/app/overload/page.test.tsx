import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import OverloadPage from "./page";

describe("OverloadPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    replace.mockReset();
    window.history.replaceState(null, "", "/");
  });

  it("erklärt die Überlast und kehrt zur gemerkten Seite zurück, sobald wieder Platz ist", async () => {
    window.history.replaceState(null, "", "/overload?from=%2Fprotocols%3Ftab%3Dopen");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify({ code: "overloaded" }), { status: 503 }));
    fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true }), { status: 200 }));
    render(<OverloadPage />);

    expect(screen.getByRole("heading", { name: "Die Server sind gerade überlastet" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Jetzt erneut versuchen" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(replace).not.toHaveBeenCalled();

    await waitFor(() => expect(screen.getByRole("button", { name: "Jetzt erneut versuchen" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Jetzt erneut versuchen" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/protocols?tab=open"));
  });

  it("springt nie auf fremde Ziele zurück", async () => {
    window.history.replaceState(null, "", "/overload?from=%2F%2Fevil.example");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    render(<OverloadPage />);

    fireEvent.click(screen.getByRole("button", { name: "Jetzt erneut versuchen" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });
});
