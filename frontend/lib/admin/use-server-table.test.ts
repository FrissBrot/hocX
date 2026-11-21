import { describe, expect, it } from "vitest";

import { serverTableApiQuery, serverTableStateFromParams, serverTableUrlQuery, type ServerTableConfig } from "./use-server-table";

type Filters = { tenant_id: string; q: string; status: string };

const config: ServerTableConfig<Filters> = {
  path: "/api/admin/x",
  pageSize: 50,
  defaults: { tenant_id: "", q: "", status: "" },
  textKey: "q",
  sortKeys: ["name", "created"],
  validate: { status: (value) => ["open", "done"].includes(value) },
  apiNames: { status: "state" },
};

describe("useServerTable (Plan §5.1)", () => {
  it("übernimmt nur gültige Werte aus der URL", () => {
    const state = serverTableStateFromParams(new URLSearchParams("status=kaputt&tenant_id=abc&offset=100&sort=unbekannt&dir=desc"), config);
    expect(state.filters.status).toBe("");
    expect(state.filters.tenant_id).toBe("abc");
    expect(state.offset).toBe(100);
    expect(state.sort).toBe("name");
    expect(state.dir).toBe("desc");
  });

  it("schreibt den Freitext ohne syncTextToUrl nie in die URL (Personendaten)", () => {
    const state = serverTableStateFromParams(new URLSearchParams("q=anna@example.com"), config);
    expect(state.filters.q).toBe("");
    const url = serverTableUrlQuery({ ...state, filters: { ...state.filters, q: "anna@example.com", status: "open" } }, config);
    expect(url.get("q")).toBeNull();
    expect(url.get("status")).toBe("open");
  });

  it("schickt den Freitext und alle Filter an die API, mit eigenem Namen", () => {
    const query = serverTableApiQuery({ filters: { tenant_id: "t1", q: " anna ", status: "open" }, offset: 50, sort: "created", dir: "desc" }, config);
    expect(query.get("q")).toBe("anna");
    expect(query.get("state")).toBe("open");
    expect(query.get("status")).toBeNull();
    expect(query.get("limit")).toBe("50");
    expect(query.get("offset")).toBe("50");
    expect(query.get("sort")).toBe("created");
  });

  it("lässt Standardwerte aus der URL weg", () => {
    const state = serverTableStateFromParams(new URLSearchParams(""), config);
    expect(serverTableUrlQuery(state, config).toString()).toBe("");
  });

  it("synchronisiert Freitext nur mit syncTextToUrl", () => {
    const withText = { ...config, syncTextToUrl: true };
    const state = serverTableStateFromParams(new URLSearchParams("q=user.login"), withText);
    expect(state.filters.q).toBe("user.login");
    expect(serverTableUrlQuery(state, withText).get("q")).toBe("user.login");
  });
});
