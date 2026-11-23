import { describe, expect, it } from "vitest";

import {
  DEFAULT_EVENT_FILTERS,
  eventApiQuery,
  eventFiltersFromParams,
  eventFiltersToParams,
  parsePivotToken,
  riskLevel,
  type PivotAliases,
} from "./security-events";

const TYPES = ["login.password", "login.success"];
const ALIASES: PivotAliases = { subject: ["konto"], net: ["netz"], device: ["gerät"], country: ["land"] };

describe("Ereignisfilter (URL, Token)", () => {
  it("übernimmt nur gültige Werte aus der URL", () => {
    const filters = eventFiltersFromParams(
      new URLSearchParams("range=7d&outcome=blocked&type=login.success&net=3f9a1c07be42&subject=Peter&country=nl&tenant_id=kaputt&group=net"),
      TYPES,
    );
    expect(filters).toEqual({ ...DEFAULT_EVENT_FILTERS, range: "7d", outcome: "blocked", type: "login.success", net: "3f9a1c07be42", group: "net" });
    expect(eventFiltersFromParams(new URLSearchParams("range=90d&type=erfunden"), TYPES)).toEqual(DEFAULT_EVENT_FILTERS);
  });

  it("schreibt nur Abweichungen vom Standard in die URL", () => {
    const params = eventFiltersToParams({ ...DEFAULT_EVENT_FILTERS, country: "CH" }, "0193a6f0-0000-7000-8000-000000000001");
    expect(params.toString()).toBe("country=CH&event=0193a6f0-0000-7000-8000-000000000001");
    expect(eventFiltersToParams(DEFAULT_EVENT_FILTERS, "kein-uuid").toString()).toBe("");
  });

  it("API-Query enthält immer den Zeitraum", () => {
    const query = eventApiQuery({ ...DEFAULT_EVENT_FILTERS, type: "login.password", subject: "abcd" }, { limit: 50 });
    expect(query.get("range")).toBe("24h");
    expect(query.get("event_type")).toBe("login.password");
    expect(query.get("subject")).toBe("abcd");
    expect(query.get("limit")).toBe("50");
  });

  it("liest Tokens mit Code oder übersetztem Namen", () => {
    expect(parsePivotToken("netz:3F9A1C07", ALIASES)).toEqual({ key: "net", value: "3f9a1c07" });
    expect(parsePivotToken(" subject: abcd1234 ", ALIASES)).toEqual({ key: "subject", value: "abcd1234" });
    expect(parsePivotToken("land:ch", ALIASES)).toEqual({ key: "country", value: "CH" });
    expect(parsePivotToken("Gerät:a03f1c", ALIASES)).toEqual({ key: "device", value: "a03f1c" });
    expect(parsePivotToken("netz:abc", ALIASES)).toBeNull();
    expect(parsePivotToken("person:timo", ALIASES)).toBeNull();
    expect(parsePivotToken("3f9a1c07", ALIASES)).toBeNull();
  });

  it("ordnet Risiko-Klassen zu", () => {
    expect(riskLevel(null)).toBeNull();
    expect(riskLevel(10)).toBe("normal");
    expect(riskLevel(30)).toBe("moderate");
    expect(riskLevel(60)).toBe("high");
    expect(riskLevel(95)).toBe("critical");
  });
});
