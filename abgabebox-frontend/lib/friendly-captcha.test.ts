import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FRIENDLY_CAPTCHA_SCRIPT_ID,
  loadFriendlyChallenge,
  mountFriendlyCaptcha,
  resetFriendlyChallengeLoaderForTests,
  type FriendlyCaptchaWidgetOptions,
  type FriendlyChallengeApi,
} from "./friendly-captcha";

// Minimales DOM-Double (kein jsdom in dieser App): nur was loader/mount wirklich anfassen.
type Listener = () => void;
class FakeElement {
  id = "";
  src = "";
  type = "";
  async = false;
  className = "";
  dataset: Record<string, string> = {};
  parentNode: FakeElement | null = null;
  children: FakeElement[] = [];
  listeners: Record<string, Listener[]> = {};
  constructor(public tagName: string, public ownerDocument: FakeDocument) {}
  appendChild(child: FakeElement) {
    child.parentNode = this;
    this.children.push(child);
    if (child.id) this.ownerDocument.byId.set(child.id, child);
    return child;
  }
  remove() {
    if (!this.parentNode) return;
    if (this.id) this.ownerDocument.byId.delete(this.id);
    this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
    this.parentNode = null;
  }
  addEventListener(name: string, fn: Listener) {
    (this.listeners[name] ??= []).push(fn);
  }
  fire(name: string) {
    for (const fn of this.listeners[name] ?? []) fn();
  }
}
class FakeDocument {
  byId = new Map<string, FakeElement>();
  body = new FakeElement("body", this);
  createElement(tag: string) {
    return new FakeElement(tag, this);
  }
  getElementById(id: string) {
    return this.byId.get(id) ?? null;
  }
}

function fakeApi() {
  const instances: { element: FakeElement; options: FriendlyCaptchaWidgetOptions; destroyed: boolean }[] = [];
  class WidgetInstance {
    entry: (typeof instances)[number];
    constructor(element: FakeElement, options: FriendlyCaptchaWidgetOptions) {
      this.entry = { element, options, destroyed: false };
      instances.push(this.entry);
    }
    destroy() {
      this.entry.destroyed = true;
      this.entry.element.remove();
    }
    reset() {}
  }
  return { api: { WidgetInstance } as unknown as FriendlyChallengeApi, instances };
}

afterEach(() => {
  resetFriendlyChallengeLoaderForTests();
});

describe("mountFriendlyCaptcha", () => {
  it("erzeugt bei jeder Montage ein neues Widget und raeumt es wieder ab", () => {
    const doc = new FakeDocument();
    const container = doc.createElement("div");
    const { api, instances } = fakeApi();
    const solved = vi.fn();

    // Erstes Element: Widget anlegen, loesen, abbauen (Client-Navigation zum naechsten Element).
    const unmountFirst = mountFriendlyCaptcha(container as unknown as HTMLElement, api, { sitekey: "sk", language: "de", onSolved: solved });
    expect(instances).toHaveLength(1);
    const host = instances[0].element;
    expect(host.className).toBe("frc-captcha");
    // Auto-Init des Vendor-Skripts darf dasselbe Element nicht zusaetzlich belegen.
    expect(host.dataset.attached).toBe("1");
    expect(instances[0].options.startMode).toBe("auto");
    instances[0].options.doneCallback("loesung-1");
    expect(solved).toHaveBeenCalledWith("loesung-1");
    unmountFirst();
    expect(instances[0].destroyed).toBe(true);
    expect(container.children).toHaveLength(0);

    // Zweites Element bzw. Neustart nach abgelaufenem Token: wieder ein frisches Widget.
    const unmountSecond = mountFriendlyCaptcha(container as unknown as HTMLElement, api, { sitekey: "sk", language: "en", onSolved: solved });
    expect(instances).toHaveLength(2);
    expect(instances[1].options.language).toBe("en");
    expect(container.children).toHaveLength(1);
    unmountSecond();
    expect(container.children).toHaveLength(0);
  });
});

describe("loadFriendlyChallenge", () => {
  it("haengt das Skript nur einmal ein und liefert die API nach dem Laden", async () => {
    const doc = new FakeDocument();
    const win: { friendlyChallenge?: FriendlyChallengeApi } = {};
    const first = loadFriendlyChallenge(doc as unknown as Document, win);
    const second = loadFriendlyChallenge(doc as unknown as Document, win);
    expect(doc.body.children).toHaveLength(1);
    const script = doc.getElementById(FRIENDLY_CAPTCHA_SCRIPT_ID)!;
    const { api } = fakeApi();
    win.friendlyChallenge = api;
    script.fire("load");
    await expect(first).resolves.toBe(api);
    await expect(second).resolves.toBe(api);
    // Spaetere Montagen (anderes Element) bekommen die API sofort, ohne neues Skript.
    await expect(loadFriendlyChallenge(doc as unknown as Document, win)).resolves.toBe(api);
    expect(doc.body.children).toHaveLength(1);
  });

  it("erlaubt nach einem Ladefehler einen neuen Versuch", async () => {
    const doc = new FakeDocument();
    const win: { friendlyChallenge?: FriendlyChallengeApi } = {};
    const failing = loadFriendlyChallenge(doc as unknown as Document, win);
    doc.getElementById(FRIENDLY_CAPTCHA_SCRIPT_ID)!.fire("error");
    await expect(failing).rejects.toThrow();
    expect(doc.body.children).toHaveLength(0);
    const retry = loadFriendlyChallenge(doc as unknown as Document, win);
    const { api } = fakeApi();
    win.friendlyChallenge = api;
    doc.getElementById(FRIENDLY_CAPTCHA_SCRIPT_ID)!.fire("load");
    await expect(retry).resolves.toBe(api);
  });
});
