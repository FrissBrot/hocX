import { describe, expect, it } from "vitest";

import { autoDisplayName, withNameUpdate } from "./display-name";

const empty = { first_name: "", last_name: "", display_name: "" };

describe("withNameUpdate", () => {
  it("fills the display name from first and last name while typing", () => {
    const first = withNameUpdate(empty, { first_name: "Test" });
    expect(first.display_name).toBe("Test");
    expect(withNameUpdate(first, { last_name: "Timo" }).display_name).toBe("Test Timo");
  });

  it("keeps a display name changed by hand", () => {
    const typed = { first_name: "Test", last_name: "Timo", display_name: "Timo W." };
    expect(withNameUpdate(typed, { last_name: "Weber" })).toEqual({ first_name: "Test", last_name: "Weber", display_name: "Timo W." });
  });

  it("follows the names again once the display name matches them", () => {
    const cleared = { first_name: "Test", last_name: "Timo", display_name: "Test Timo" };
    expect(withNameUpdate(cleared, { first_name: "Anna" }).display_name).toBe("Anna Timo");
    expect(autoDisplayName("  Anna ", "")).toBe("Anna");
  });
});
