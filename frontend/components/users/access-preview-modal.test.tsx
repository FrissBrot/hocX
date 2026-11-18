import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { AccessPreviewModal } from "./access-preview-modal";
import type { AccessPreview } from "@/types/api";

const PREVIEW: AccessPreview = {
  user_id: "u1",
  display_name: "Prüfer Paula",
  is_active: true,
  login_enabled: true,
  roles: [{ id: "r1", name: "Prüfer", system_key: null }],
  permissions: [
    { key: "meetings.read", scope: null, feature_access: "full", effective: true },
    { key: "submissions.read", scope: "assigned", feature_access: "full", effective: true },
    { key: "submissions.review", scope: "assigned", feature_access: "full", effective: true },
  ],
  enabled_features: ["abgabebox"],
  read_only_features: [],
  mfa_required: true,
  mfa_active: false,
  submissions: { scope: "assigned", visible_count: 1, assigned: [{ id: "a1", title: "Berichte" }] },
};

describe("AccessPreviewModal («Ansehen als …», Phase 7)", () => {
  beforeEach(() => browserApiFetchMock.mockReset());

  it("lädt nur die Vorschau-Route und zeigt Menüpunkte, Reichweite, MFA und Abgaben", async () => {
    browserApiFetchMock.mockResolvedValue(PREVIEW);
    render(<AccessPreviewModal open onClose={() => undefined} userId="u1" name="Prüfer Paula" />);

    expect(await screen.findByText("Berichte")).toBeTruthy();
    expect(browserApiFetchMock).toHaveBeenCalledTimes(1);
    expect(browserApiFetchMock.mock.calls[0]).toEqual(["/api/users/u1/access-preview"]);
    // Navigation aus buildNav: Abgaben (submissions.read) und Kalender (meetings.read)
    expect(screen.getByText("Kalender")).toBeTruthy();
    expect(screen.getAllByText("Nur zugewiesene").length).toBe(2);
    expect(screen.getByText("MFA Pflicht")).toBeTruthy();
    expect(screen.getByText("Nur zugewiesene Abgabe-Aufträge: 1")).toBeTruthy();
    // Keine Finanzen ohne Recht
    expect(screen.queryByText("Kassenbuch ansehen")).toBeNull();
  });
});
