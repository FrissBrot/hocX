import { Activity } from "react";
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRefreshOnRestore } from "./use-refresh-on-restore";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function ListPage() {
  useRefreshOnRestore();
  return null;
}

beforeEach(() => router.refresh.mockClear());

describe("useRefreshOnRestore", () => {
  it("aktualisiert eine aus dem App-Router-Cache wiederangezeigte Liste", () => {
    const { rerender } = render(<Activity mode="visible"><ListPage /></Activity>);
    router.refresh.mockClear();
    rerender(<Activity mode="hidden"><ListPage /></Activity>);
    expect(router.refresh).not.toHaveBeenCalled();
    rerender(<Activity mode="visible"><ListPage /></Activity>);
    expect(router.refresh).toHaveBeenCalledTimes(1);
    rerender(<Activity mode="visible"><ListPage /></Activity>);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("aktualisiert beim erneuten Mounten nach einer Navigation", () => {
    const page = render(<ListPage />);
    page.unmount();
    router.refresh.mockClear();
    render(<ListPage />);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("behandelt den Browsercache und entfernt den Listener beim Verlassen", () => {
    const page = render(<ListPage />);
    router.refresh.mockClear();
    act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false })));
    expect(router.refresh).not.toHaveBeenCalled();
    act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
    expect(router.refresh).toHaveBeenCalledTimes(1);
    page.unmount();
    act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });
});
