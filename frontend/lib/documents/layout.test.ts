import { describe, expect, it } from "vitest";

import { contentFixture, text } from "@/lib/documents/test/content-fixture";
import { areaNodes, countNodes, duplicateNode, insertNode, isAncestor, locate, moveNode, moveWithinParent, pageDimensions, removeNode, repeatScope, updateNode, withFreshIds } from "./layout";

const ids = (nodes: { id: string }[]) => nodes.map((node) => node.id);

describe("layout tree operations", () => {
  it("locates nodes in every area with parent and depth", () => {
    const content = contentFixture();
    expect(locate(content, "inner-2")).toMatchObject({ area: "body", parentId: "sec", index: 1, depth: 1 });
    expect(locate(content, "hdr-title")).toMatchObject({ area: "master:default:header", parentId: null, index: 0 });
    expect(locate(content, "missing")).toBeNull();
    expect(countNodes(content)).toBe(7);
  });

  it("inserts, updates and removes without mutating the previous snapshot", () => {
    const original = contentFixture();
    const inserted = insertNode(original, "body", "sec", 1, text("new", "Neu"));
    expect(ids(locate(inserted, "sec")!.node.children!)).toEqual(["inner-1", "new", "inner-2"]);
    expect(ids(locate(original, "sec")!.node.children!)).toEqual(["inner-1", "inner-2"]);

    const updated = updateNode(inserted, "new", { name: "Hinweis" });
    expect(locate(updated, "new")!.node.name).toBe("Hinweis");
    expect(locate(inserted, "new")!.node.name).toBeUndefined();

    const removed = removeNode(updated, "new");
    expect(locate(removed, "new")).toBeNull();
  });

  it("never removes locked nodes", () => {
    const content = contentFixture();
    expect(removeNode(content, "fixed")).toBe(content);
  });

  it("moves nodes between containers and areas and corrects the index within the same parent", () => {
    const content = contentFixture();
    const down = moveNode(content, "intro", "body", null, 2);
    expect(ids(down.body)).toEqual(["sec", "intro", "fixed"]);

    const intoSection = moveNode(content, "intro", "body", "sec", 0);
    expect(ids(intoSection.body)).toEqual(["sec", "fixed"]);
    expect(ids(locate(intoSection, "sec")!.node.children!)).toEqual(["intro", "inner-1", "inner-2"]);

    const toFooter = moveNode(content, "inner-1", "master:default:footer", null, 0);
    expect(ids(areaNodes(toFooter, "master:default:footer"))).toEqual(["inner-1", "pno"]);
  });

  it("refuses to move a container into its own descendant", () => {
    const content = contentFixture();
    expect(isAncestor(content, "sec", "inner-1")).toBe(true);
    expect(moveNode(content, "sec", "body", "inner-1", 0)).toBe(content);
    expect(moveNode(content, "sec", "body", "sec", 0)).toBe(content);
  });

  it("moves within the parent by one step and stops at the edges", () => {
    const content = contentFixture();
    expect(ids(locate(moveWithinParent(content, "inner-1", 1), "sec")!.node.children!)).toEqual(["inner-2", "inner-1"]);
    expect(moveWithinParent(content, "inner-1", -1)).toBe(content);
  });

  it("duplicates with fresh ids for the whole subtree and unlocks the copy", () => {
    const content = contentFixture();
    const { content: next, newId } = duplicateNode(content, "sec");
    expect(next.body).toHaveLength(4);
    const copy = locate(next, newId!)!.node;
    expect(locate(next, newId!)!.index).toBe(2);
    expect(copy.id).not.toBe("sec");
    expect(ids(copy.children!)).not.toContain("inner-1");
    expect(copy.locked).toBe(false);
  });

  it("gives table columns new ids when copying", () => {
    const node = withFreshIds({ id: "t", type: "table", columns: [{ id: "c1" }, { id: "c2" }] });
    const columnIds = (node.columns as { id: string }[]).map((column) => column.id);
    expect(columnIds).not.toContain("c1");
    expect(new Set(columnIds).size).toBe(2);
  });

  it("finds the repeat scope of nested nodes", () => {
    const content = updateNode(contentFixture(), "sec", { repeat: { source: "todos.open", limit: 50 } });
    expect(repeatScope(content, "inner-1")).toBe("todos.open");
    expect(repeatScope(content, "intro")).toBeNull();
  });

  it("computes page dimensions for paper sizes and orientation", () => {
    const page = contentFixture().page;
    expect(pageDimensions(page)).toEqual([210, 297]);
    expect(pageDimensions(page, "landscape")).toEqual([297, 210]);
    expect(pageDimensions({ ...page, size: "custom", width: 300, height: 100 })).toEqual([100, 300]);
  });
});
