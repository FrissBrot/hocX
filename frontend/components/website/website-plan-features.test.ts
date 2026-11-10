import { describe, expect, it } from "vitest";

import type { PublicPlan } from "@/types/api";

import { planFeatureLines, yearlySavings } from "./website-plan-features";

const t = (key: string, values?: Record<string, string | number>) => (values ? `${key}:${JSON.stringify(values)}` : key);

function plan(overrides: Partial<PublicPlan>): PublicPlan {
  return {
    code: "p",
    name: "P",
    description: null,
    price_monthly_rp: 1900,
    price_yearly_rp: 19000,
    included_user_limit: 5,
    included_storage_bytes: 2 * 1024 ** 3,
    is_featured: false,
    features: [],
    ...overrides,
  };
}

describe("planFeatureLines", () => {
  it("fasst die Module des guenstigeren Plans als 'Alles aus' zusammen", () => {
    const start = plan({ name: "Start", features: [{ code: "abgabebox", name: "Abgabebox" }] });
    const team = plan({
      name: "Team",
      included_user_limit: null,
      included_storage_bytes: null,
      features: [
        { code: "abgabebox", name: "Abgabebox" },
        { code: "finance", name: "Finanzen" },
      ],
    });

    expect(planFeatureLines(team, start, t)).toEqual([
      'everythingFrom:{"plan":"Start"}',
      "Finanzen",
      "usersUnlimited",
      "storageUnlimited",
    ]);
  });

  it("listet alle Module, wenn der vorherige Plan nicht enthalten ist", () => {
    const lines = planFeatureLines(plan({ features: [{ code: "finance", name: "Finanzen" }] }), null, t);
    expect(lines).toEqual(["Finanzen", 'usersUpTo:{"count":5}', 'storageGb:{"gb":2}']);
  });
});

describe("yearlySavings", () => {
  it("meldet gleiche Gratismonate bei allen Plaenen", () => {
    expect(yearlySavings([plan({}), plan({ price_monthly_rp: 4900, price_yearly_rp: 49000 })])).toEqual({ months: 2 });
  });

  it("faellt auf die maximale Ersparnis in Prozent zurueck", () => {
    expect(yearlySavings([plan({}), plan({ price_monthly_rp: 1000, price_yearly_rp: 11000 })])).toEqual({ percent: 17 });
  });

  it("liefert nichts ohne Jahrespreise", () => {
    expect(yearlySavings([plan({ price_yearly_rp: null })])).toBeNull();
  });
});
