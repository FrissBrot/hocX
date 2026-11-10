import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProtocolCollaboration } from "./use-protocol-collaboration";

// Fake-WebSocket: close() feuert onclose wie im Browser asynchron.
class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send() {}
  close() {
    this.closed = true;
    this.readyState = 3;
    setTimeout(() => this.onclose?.(), 0);
  }
}

describe("useProtocolCollaboration (Audit MAIN-FE-008)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("oeffnet nach Protokollwechsel genau eine Verbindung und plant keinen Reconnect", () => {
    const { rerender, unmount } = renderHook(({ id }) => useProtocolCollaboration(id), { initialProps: { id: "p1" } });
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ id: "p2" });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[0].closed).toBe(true);

    // Das verspaetete onclose des alten Sockets und alle Reconnect-Timer laufen ab.
    act(() => { vi.advanceTimersByTime(60_000); });

    expect(FakeWebSocket.instances).toHaveLength(2);
    const open = FakeWebSocket.instances.filter((socket) => !socket.closed);
    expect(open).toHaveLength(1);
    expect(open[0].url).toContain("p2");

    unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances.every((socket) => socket.closed)).toBe(true);
  });
});
