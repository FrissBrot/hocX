// MFA einrichten/entfernen (Profil und Plattform-Admin): Fehler des Backends kamen als rohe
// deutsche Meldung in den Toast («Der TOTP-Code ist nicht gültig»), obwohl es für den Code eine
// Übersetzung in security.apiErrors gibt.
import fs from "node:fs";
import path from "node:path";

import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  browserApiFetch: (url: string, init?: unknown) => api(url, init),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "en");
  const messages = Object.fromEntries(
    fs.readdirSync(dir).filter((file) => file.endsWith(".json")).map((file) => [file.replace(/\.json$/, ""), JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"))]),
  );
  return { ...actual, useTranslations: (namespace?: string) => actual.createTranslator({ locale: "en", messages, namespace }), useLocale: () => "en" };
});

import { useMfaEnrollment } from "./use-mfa-enrollment";

it("shows a wrong TOTP code during setup in the UI language", async () => {
  api.mockImplementation((url: string) => {
    if (url.endsWith("/totp/start")) return Promise.resolve({ flow_token: "f", secret: "S", manual_entry_key: "S", otpauth_uri: "otpauth://x" });
    return Promise.reject(new ApiError("Der TOTP-Code ist nicht gültig", "validation", 400, { code: "totp_invalid", message: "Der TOTP-Code ist nicht gültig" }));
  });
  const { result } = renderHook(() => useMfaEnrollment("/api/users/me/mfa", null, vi.fn()));
  await act(() => result.current.startTotp());
  await act(() => result.current.completeTotp());
  expect(toast).toHaveBeenLastCalledWith("The code is not valid. Please check your device's time and try again.", "error");
});
