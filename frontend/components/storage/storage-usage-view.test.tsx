import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StorageUsageRead } from "@/types/api";

import { StorageBreakdown } from "./storage-usage-view";

function usage(overrides: Partial<StorageUsageRead> = {}): StorageUsageRead {
  return {
    total_bytes: 800,
    quota_bytes: 1000,
    categories: [
      { key: "photos", label: "Fotos", bytes: 500 },
      { key: "files", label: "Dateien", bytes: 300 },
    ],
    ...overrides,
  };
}

describe("StorageBreakdown", () => {
  it("sizes segments against the quota (not just the used total) when a quota is set", () => {
    const { container } = render(<StorageBreakdown {...usage()} />);

    const segments = container.querySelectorAll(".storage-usage-segment:not(.storage-usage-segment-free)");
    // 500/1000 and 300/1000 - the quota (1000), not the used total (800), is the
    // denominator whenever quota > total.
    expect((segments[0] as HTMLElement).style.width).toBe("50%");
    expect((segments[1] as HTMLElement).style.width).toBe("30%");
  });

  it("renders a free-space segment sized to quota minus used, once a quota is set", () => {
    const { container } = render(<StorageBreakdown {...usage()} />);

    const freeSegment = container.querySelector(".storage-usage-segment-free") as HTMLElement | null;
    expect(freeSegment).not.toBeNull();
    // (1000 - 800) / 1000
    expect(freeSegment!.style.width).toBe("20%");
  });

  it("regression (audit fix, 2026-09-17): over-quota usage sizes segments against the quota, matching the previously-diverged admin view", () => {
    // Before this component was shared, the admin modal used
    // Math.max(total, quota, 1) as the denominator instead of quota-when-over-total, so
    // an over-quota tenant's segments looked different in the admin panel than here.
    const overQuota = usage({ total_bytes: 1200, quota_bytes: 1000 });

    const { container } = render(<StorageBreakdown {...overQuota} />);

    const segments = container.querySelectorAll(".storage-usage-segment:not(.storage-usage-segment-free)");
    // barTotal is total_bytes (1200) here, since quota (1000) is NOT greater than it -
    // 500/1200 and 300/1200.
    expect((segments[0] as HTMLElement).style.width).toBe(`${(500 / 1200) * 100}%`);
    expect((segments[1] as HTMLElement).style.width).toBe(`${(300 / 1200) * 100}%`);
    // No free-space segment once already over quota.
    expect(container.querySelector(".storage-usage-segment-free")).toBeNull();
  });

  it("shows the empty-state row when every category is zero", () => {
    const { getByText } = render(<StorageBreakdown {...usage({ categories: [{ key: "other", label: "Sonstiges", bytes: 0 }] })} />);

    expect(getByText("Noch keine Dateien vorhanden.")).toBeInTheDocument();
  });
});
