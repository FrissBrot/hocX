import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dispatchShortcut, resetShortcutRegistrationsForTests, useShortcut } from "./use-shortcut";

function press(target: EventTarget, init: KeyboardEventInit) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

afterEach(() => {
  resetShortcutRegistrationsForTests();
  document.body.innerHTML = "";
});

describe("Shortcut-Dispatcher", () => {
  it("löst einen globalen Shortcut genau einmal aus und verhindert den Browser-Standard", () => {
    const handler = vi.fn();
    renderHook(() => useShortcut("global.search", handler));
    const event = press(document.body, { key: "k", ctrlKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("Einbuchstaben-Kürzel bleiben beim Tippen aus, Kürzel mit inInputs nicht", () => {
    const help = vi.fn();
    const search = vi.fn();
    renderHook(() => useShortcut("global.help", help));
    renderHook(() => useShortcut("global.search", search));
    document.body.innerHTML = '<input id="field" /><div contenteditable="true" id="editor"></div><input type="checkbox" id="box" />';
    press(document.getElementById("field")!, { key: "?", shiftKey: true });
    press(document.getElementById("editor")!, { key: "?", shiftKey: true });
    expect(help).not.toHaveBeenCalled();
    press(document.getElementById("box")!, { key: "?", shiftKey: true });
    expect(help).toHaveBeenCalledTimes(1);
    press(document.getElementById("field")!, { key: "k", ctrlKey: true });
    expect(search).toHaveBeenCalledTimes(1);
  });

  it("Seiten-Scope hat Vorrang vor global, kein doppeltes Auslösen", () => {
    const global = vi.fn();
    const page = vi.fn();
    renderHook(() => useShortcut("global.listSearch", global));
    renderHook(() => useShortcut("protocol.find", page));
    press(document.body, { key: "f", ctrlKey: true });
    expect(page).toHaveBeenCalledTimes(1);
    expect(global).not.toHaveBeenCalled();
  });

  it("gibt ein Handler `false` zurück, ist die nächste Bindung dran bzw. der Browser", () => {
    const page = vi.fn(() => false as const);
    const global = vi.fn(() => false as const);
    renderHook(() => useShortcut("global.listSearch", global));
    renderHook(() => useShortcut("protocol.find", page));
    const event = press(document.body, { key: "f", ctrlKey: true });
    expect(page).toHaveBeenCalledTimes(1);
    expect(global).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(false);
  });

  it("ein offener Dialog sperrt Seiten-Kürzel, ausser sie gehören zum Dialog", () => {
    const page = vi.fn();
    renderHook(() => useShortcut("protocol.nextElement", page));
    document.body.innerHTML = '<div role="dialog" aria-modal="true"><button id="inside">x</button></div>';
    press(document.getElementById("inside")!, { key: "Enter", ctrlKey: true });
    expect(page).not.toHaveBeenCalled();

    const scope = { current: document.querySelector<HTMLElement>('[role="dialog"]') };
    const viewer = vi.fn();
    renderHook(() => useShortcut("media.next", viewer, { scopeRef: scope }));
    press(document.getElementById("inside")!, { key: "ArrowRight" });
    expect(viewer).toHaveBeenCalledTimes(1);
  });

  it("Pfeile in einem Listen-/Menü-Widget gehören dem Widget", () => {
    const page = vi.fn();
    renderHook(() => useShortcut("protocol.elementDown", page));
    document.body.innerHTML = '<div role="listbox"><div role="option" tabindex="0" id="option">a</div></div><button id="plain">b</button>';
    press(document.getElementById("option")!, { key: "ArrowDown" });
    expect(page).not.toHaveBeenCalled();
    press(document.getElementById("plain")!, { key: "ArrowDown" });
    expect(page).toHaveBeenCalledTimes(1);
  });

  it("ignoriert IME-Komposition und schon behandelte Ereignisse", () => {
    const handler = vi.fn();
    renderHook(() => useShortcut("global.search", handler));
    press(document.body, { key: "k", ctrlKey: true, isComposing: true });
    const handled = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, cancelable: true });
    handled.preventDefault();
    expect(dispatchShortcut(handled)).toBe(false);
    expect(handler).not.toHaveBeenCalled();
  });

  it("entfernt die Bindung beim Unmount und wenn sie deaktiviert wird", () => {
    const handler = vi.fn();
    const hook = renderHook(({ enabled }) => useShortcut("global.search", handler, { enabled }), { initialProps: { enabled: true } });
    hook.rerender({ enabled: false });
    press(document.body, { key: "k", ctrlKey: true });
    hook.unmount();
    press(document.body, { key: "k", ctrlKey: true });
    expect(handler).not.toHaveBeenCalled();
  });
});
