import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { INSTALL_DISMISS_KEY } from "@/lib/pwa/install";

import { InstallAppPrompt } from "./install-app-prompt";

const pathname = { value: "/" };
vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1";

beforeEach(() => {
  vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(IPHONE);
  window.localStorage.clear();
  pathname.value = "/";
});

afterEach(() => vi.restoreAllMocks());

it("schlägt auf dem iPhone die Installation vor und merkt sich das Schliessen", async () => {
  const { unmount } = render(<InstallAppPrompt />);
  await waitFor(() => expect(screen.getByText("hocX als App installieren")).toBeTruthy());
  expect(screen.getByText(/Zum Home-Bildschirm/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Hinweis schliessen" }));
  expect(screen.queryByText("hocX als App installieren")).toBeNull();
  expect(window.localStorage.getItem(INSTALL_DISMISS_KEY)).not.toBeNull();
  unmount();

  render(<InstallAppPrompt />);
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(screen.queryByText("hocX als App installieren")).toBeNull();
});

it("stört nicht im Protokoll-Editor und nicht am Desktop", async () => {
  pathname.value = "/protocols/0190a000-0000-7000-8000-000000000001";
  const { unmount } = render(<InstallAppPrompt />);
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(screen.queryByText("hocX als App installieren")).toBeNull();
  unmount();

  pathname.value = "/";
  vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140");
  render(<InstallAppPrompt />);
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(screen.queryByText("hocX als App installieren")).toBeNull();
});
