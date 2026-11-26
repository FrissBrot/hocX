// Profil › Sicherheit › MFA: Die Standardmethode kam als fertiger deutscher Text aus dem Backend
// (`preferred_factor_label`: «Authenticator-App», «2 Authenticator-Apps») und stand so auch in
// der englischen, französischen und italienischen Oberfläche.
import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: unknown) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "en");
  const messages = Object.fromEntries(
    fs.readdirSync(dir).filter((file) => file.endsWith(".json")).map((file) => [file.replace(/\.json$/, ""), JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"))]),
  );
  return { ...actual, useTranslations: (namespace?: string) => actual.createTranslator({ locale: "en", messages, namespace }), useLocale: () => "en" };
});

import { MfaProfilePanel } from "./mfa-profile-panel";

it("shows the default method in the UI language, not the German backend label", async () => {
  api.mockResolvedValue({
    required: false,
    has_factors: true,
    can_add_passkey_here: true,
    preferred_factor_type: "totp",
    preferred_factor_label: "2 Authenticator-Apps",
    factors: [
      { id: "f1", factor_type: "totp", label: "Phone", created_at: "2026-11-01T08:00:00Z", last_used_at: null },
      { id: "f2", factor_type: "totp", label: "Tablet", created_at: "2026-11-02T08:00:00Z", last_used_at: null },
    ],
  });
  render(<MfaProfilePanel open />);
  expect(await screen.findByText("Login default: TOTP")).toBeInTheDocument();
  expect(screen.queryByText(/Authenticator-Apps?/)).toBeNull();
});
