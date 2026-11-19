import { describe, expect, it } from "vitest";

import { eventFieldSelectionPatch, mergeEventPatches, toggleRolePatch } from "./event-patch";

const roles = { organizer_ids: null, leadership_ids: null, participant_ids: ["a"], spezial1_ids: null, spezial2_ids: null, spezial3_ids: null };

describe("toggleRolePatch", () => {
  it("adds a person and sends the base it started from", () => {
    expect(toggleRolePatch(roles, "participant_ids", "b")).toEqual({ participant_ids: ["a", "b"], role_ids_base: { participant_ids: ["a"] } });
  });

  it("removes a person and treats an empty list as base", () => {
    expect(toggleRolePatch(roles, "participant_ids", "a")).toEqual({ participant_ids: [], role_ids_base: { participant_ids: ["a"] } });
    expect(toggleRolePatch(roles, "organizer_ids", "x")).toEqual({ organizer_ids: ["x"], role_ids_base: { organizer_ids: [] } });
  });
});

describe("mergeEventPatches", () => {
  it("keeps the oldest base per field and the newest value", () => {
    const first = toggleRolePatch(roles, "participant_ids", "b");
    const second = toggleRolePatch({ ...roles, participant_ids: ["a", "b"] }, "participant_ids", "c");
    expect(mergeEventPatches(first, second)).toEqual({ participant_ids: ["a", "b", "c"], role_ids_base: { participant_ids: ["a"] } });
  });

  it("combines bases of different fields and plain fields", () => {
    const merged = mergeEventPatches({ title: "Alt", role_ids_base: { organizer_ids: [] }, organizer_ids: ["x"] }, { participant_ids: ["a", "b"], role_ids_base: { participant_ids: ["a"] }, title: "Neu" });
    expect(merged).toEqual({ title: "Neu", organizer_ids: ["x"], participant_ids: ["a", "b"], role_ids_base: { organizer_ids: [], participant_ids: ["a"] } });
  });

  it("leaves patches without base unchanged", () => {
    expect(mergeEventPatches(undefined, { title: "x" })).toEqual({ title: "x" });
  });
});

describe("eventFieldSelectionPatch", () => {
  it("adds the base only for role fields", () => {
    expect(eventFieldSelectionPatch("leadership_ids", ["a", "b"], ["a"])).toEqual({ leadership_ids: ["a", "b"], role_ids_base: { leadership_ids: ["a"] } });
    expect(eventFieldSelectionPatch("other_ids", ["a"], [])).toEqual({ other_ids: ["a"] });
    expect(eventFieldSelectionPatch("participant_ids", ["a"])).toEqual({ participant_ids: ["a"] });
  });
});
