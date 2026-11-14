import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) }));

import BridgePage from "./page";

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/auth/bridge#token=brueckentoken");
  api.mockImplementation((url: string) =>
    Promise.resolve(url.endsWith("/preview")
      ? { display_name: "Neu Person", email: "neu@example.com", tenant_name: "Pfadi Test" }
      : { status: "ok" }));
});

it("asks for confirmation and sends the fragment token only in the body", async () => {
  render(<BridgePage />);
  expect(await screen.findByText(/Als Neu Person \(neu@example.com\) bei Pfadi Test anmelden\?/)).toBeInTheDocument();
  expect(window.location.hash).toBe("");
  expect(api).toHaveBeenCalledWith("/api/auth/bridge/preview", { method: "POST", body: JSON.stringify({ token: "brueckentoken" }) });
});

it("keeps the token under React StrictMode (effects run twice in development)", async () => {
  render(<StrictMode><BridgePage /></StrictMode>);
  expect(await screen.findByText(/Als Neu Person/)).toBeInTheDocument();
  expect(screen.queryByText(/ungültig oder abgelaufen/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/auth/bridge", { method: "POST", body: JSON.stringify({ token: "brueckentoken" }) }));
});

it("shows an invalid link without a token", async () => {
  window.history.replaceState(null, "", "/auth/bridge");
  render(<BridgePage />);
  expect(await screen.findByText(/ungültig oder abgelaufen/)).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});
