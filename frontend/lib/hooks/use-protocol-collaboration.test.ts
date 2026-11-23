import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fieldLocksSignature, useFieldLocksSignature, useProtocolCollaboration } from "./use-protocol-collaboration";

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

const BLOCK_A = "0190a000-0000-7000-8000-00000000000a";
const BLOCK_B = "0190a000-0000-7000-8000-00000000000b";

describe("Sperren ohne Neu-Rendern des ganzen Editors (Performance-Audit K1)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function receive(message: Record<string, unknown>) {
    const socket = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    act(() => socket.onmessage?.({ data: JSON.stringify(message) }));
  }

  function setup() {
    const renders = { editor: 0, a: 0, b: 0 };
    const hook = renderHook(() => {
      renders.editor += 1;
      return useProtocolCollaboration("p1");
    });
    const fieldLocks = hook.result.current.fieldLocks;
    const elementA = renderHook(() => {
      renders.a += 1;
      return useFieldLocksSignature(fieldLocks, [BLOCK_A]);
    });
    const elementB = renderHook(() => {
      renders.b += 1;
      return useFieldLocksSignature(fieldLocks, [BLOCK_B]);
    });
    receive({ type: "snapshot", self: { user_id: "me", can_edit: true }, presence: [{ user_id: "other", display_name: "Andrea" }], locks: {} });
    return { hook, elementA, elementB, renders };
  }

  it("zeigt fremde Sperren an, rendert aber nur den betroffenen Punkt neu", () => {
    const { hook, elementA, renders } = setup();
    const collabBefore = hook.result.current;
    const before = { ...renders };

    receive({ type: "lock_acquired", field_key: `block-${BLOCK_A}`, user_id: "other", display_name: "Andrea" });

    expect(hook.result.current.isLockedByOther(`block-${BLOCK_A}`)).toEqual({ user_id: "other", display_name: "Andrea" });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_B}`)).toBeNull();
    expect(hook.result.current.hasOtherActiveEditors()).toBe(true);
    // Editor-Objekt und Sperr-Schnittstelle behalten ihre Identität: die memoisierten Punkte
    // vergleichen Props nach Identität.
    expect(hook.result.current).toBe(collabBefore);
    expect(hook.result.current.fieldLocks).toBe(collabBefore.fieldLocks);
    expect(renders.editor).toBe(before.editor);
    expect(renders.b).toBe(before.b);
    expect(renders.a).toBe(before.a + 1);
    expect(elementA.result.current).toContain("Andrea");

    receive({ type: "lock_released", field_key: `block-${BLOCK_A}` });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_A}`)).toBeNull();
    expect(hook.result.current.hasOtherActiveEditors()).toBe(false);
    expect(elementA.result.current).toBe("");
  });

  it("Matrixzellen zählen zum Block, eigene Sperren lösen nichts aus", () => {
    const { hook, elementA, elementB, renders } = setup();
    const before = { ...renders };

    receive({ type: "lock_acquired", field_key: `block-${BLOCK_B}-cell-r1-c1`, user_id: "other", display_name: "Andrea" });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_B}-cell-r1-c1`)?.display_name).toBe("Andrea");
    expect(renders.a).toBe(before.a);
    expect(renders.b).toBe(before.b + 1);
    expect(elementB.result.current).toContain(`block-${BLOCK_B}-cell-r1-c1`);

    // Eigene Sperre (Fokus im eigenen Browser): kein Eintrag, kein Neu-Rendern
    act(() => hook.result.current.fieldLocks.lockField(`block-${BLOCK_A}`));
    receive({ type: "lock_acquired", field_key: `block-${BLOCK_A}`, user_id: "me", display_name: "Ich" });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_A}`)).toBeNull();
    expect(renders.a).toBe(before.a);
    expect(elementA.result.current).toBe("");
  });

  it("verweigerte Sperre zeigt den Halter, Neuverbindung setzt Sperren aus dem Snapshot", () => {
    const { hook } = setup();
    receive({ type: "lock_denied", field_key: `block-${BLOCK_A}`, holder: { user_id: "other", display_name: "Andrea" } });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_A}`)?.user_id).toBe("other");
    receive({ type: "snapshot", self: { user_id: "me" }, presence: [], locks: { [`block-${BLOCK_B}`]: { user_id: "other", display_name: "Andrea" }, [`block-${BLOCK_A}`]: { user_id: "me", display_name: "Ich" } } });
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_A}`)).toBeNull();
    expect(hook.result.current.isLockedByOther(`block-${BLOCK_B}`)?.user_id).toBe("other");
  });

  it("Anwesenheit ändert das Editor-Objekt, die Sperr-Schnittstelle bleibt gleich", () => {
    const { hook } = setup();
    const fieldLocks = hook.result.current.fieldLocks;
    receive({ type: "presence_join", user_id: "third", display_name: "Benno" });
    expect(hook.result.current.otherPresence.map((entry) => entry.display_name)).toEqual(["Andrea", "Benno"]);
    expect(hook.result.current.fieldLocks).toBe(fieldLocks);
  });

  it("Signatur ordnet Feldschlüssel nur dem eigenen Block zu", () => {
    const locks = { [`block-${BLOCK_A}`]: { user_id: "u", display_name: "U" }, [`block-${BLOCK_B}-cell-1-2`]: { user_id: "v", display_name: "V" }, "event-created": { user_id: "w", display_name: "W" } };
    expect(fieldLocksSignature(locks, new Set([BLOCK_A]))).toBe(`block-${BLOCK_A}=u:U`);
    expect(fieldLocksSignature(locks, new Set([BLOCK_B]))).toBe(`block-${BLOCK_B}-cell-1-2=v:V`);
    expect(fieldLocksSignature(locks, new Set(["0190a000-0000-7000-8000-0000000000ff"]))).toBe("");
  });
});
