import { describe, expect, it } from "vitest";

import studio from "@/lib/documents/test/studio-catalog.generated.json";
import type { SimpleCatalog } from "@/lib/documents/api";
import { conditionPreset, getPath, matchSimpleBlock, plainText, setPath, setVariant, textContent, toggleValue, variantValue } from "./simple";

const catalog = studio.catalog.simple as unknown as SimpleCatalog;

describe("simple mode helpers", () => {
  it("matches nodes to the blocks described by the backend", () => {
    expect(matchSimpleBlock(catalog, { id: "p", type: "data_block", component: "protocol_element" })?.key).toBe("protocol");
    expect(matchSimpleBlock(catalog, { id: "t", type: "text", role: "title" })?.key).toBe("title");
    expect(matchSimpleBlock(catalog, { id: "x", type: "text" })?.key).toBe("text");
    expect(matchSimpleBlock(catalog, { id: "d", type: "data_block", component: "fines" })?.key).toBe("data");
    expect(matchSimpleBlock(catalog, { id: "s", type: "section", children: [] })?.key).toBe("group");
    expect(matchSimpleBlock(catalog, { id: "a", type: "absolute_layer" })).toBeNull();
  });

  it("reads and writes settings by path without mutating the node", () => {
    const node = { id: "p", type: "data_block", component: "protocol_element", params: { titles_only: false } };
    const next = setPath(node, "params.titles_only", true);
    expect(getPath(next, "params.titles_only")).toBe(true);
    expect(node.params.titles_only).toBe(false);
    const block = matchSimpleBlock(catalog, node)!;
    const setting = block.settings.find((item) => item.key === "session_todos");
    expect(setting && setting.kind === "toggle" ? toggleValue(node, setting) : null).toBe(true);
  });

  it("keeps texts with data fields for the advanced mode", () => {
    expect(plainText({ default: [{ t: "text", v: "Hallo" }, { t: "br" }, { t: "text", v: "Welt" }] })).toBe("Hallo\nWelt");
    expect(plainText({ default: [{ t: "bind", path: "document.title" }] })).toBeNull();
    expect(plainText(textContent("A\nB"))).toBe("A\nB");
  });

  it("recognises preset conditions and block variants", () => {
    expect(conditionPreset(catalog, { id: "s", type: "section", visible_if: catalog.conditions.open_todos })).toBe("open_todos");
    expect(conditionPreset(catalog, { id: "s", type: "section", visible_if: { op: "exists", path: "x" } })).toBe("custom");
    expect(conditionPreset(catalog, { id: "s", type: "section" })).toBeNull();
    const styled = setVariant({ id: "t", type: "data_block", component: "todo_table" }, "todo", "checklist");
    expect(variantValue(styled, "todo")).toBe("checklist");
    expect(setVariant(styled, "todo", "").appearance).toEqual({});
  });
});
